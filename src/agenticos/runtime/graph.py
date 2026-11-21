"""Sequential LangGraph workflow for coding tasks."""

from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from agenticos.inference.base import ModelClient
from agenticos.runtime.progress import (
    AgentStage,
    ProgressCallback,
    RunCancelledError,
    StageEventType,
    StageProgress,
    TokenChunk,
    TokenChunkCallback,
)
from agenticos.runtime.prompts import CODER, PLANNER, REVIEWER, TEST_PLANNER
from agenticos.runtime.state import AgentState
from agenticos.runtime.tools import ToolRegistry


class CodingWorkflow:
    def __init__(
        self, model: ModelClient, *, tool_registry: ToolRegistry | None = None
    ) -> None:
        self.model = model
        self.tool_registry = tool_registry
        graph = StateGraph(AgentState)
        graph.add_node("planner", self._plan)
        graph.add_node("coder", self._code)
        graph.add_node("reviewer", self._review)
        graph.add_node("test_planner", self._test_plan)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "coder")
        graph.add_edge("coder", "reviewer")
        graph.add_edge("reviewer", "test_planner")
        graph.add_edge("test_planner", END)
        self.graph = graph.compile()

    async def execute_tool(
        self, name: str, arguments: dict[str, object], *, principal_id: str,
        workspace_id: str = "default",
    ) -> dict[str, object]:
        """Execute an explicitly requested tool through the permission-checked registry."""
        if self.tool_registry is None:
            raise RuntimeError("Agent tools are not configured")
        return await self.tool_registry.execute(
            name, arguments, principal_id=principal_id, workspace_id=workspace_id
        )

    def _emit(
        self,
        state: AgentState,
        stage: AgentStage,
        event_type: StageEventType,
        *,
        duration_ms: int | None = None,
    ) -> None:
        callback = state.get("progress_callback")
        if callback is not None:
            callback(
                StageProgress.create(
                    state.get("run_id", "untracked"),
                    stage,
                    event_type,
                    duration_ms=duration_ms,
                )
            )

    async def _generate(
        self, state: AgentState, stage: AgentStage, prompt: str, *, system: str
    ) -> str:
        token_callback = state.get("token_callback")
        stream = getattr(self.model, "generate_stream", None)
        if token_callback is None or stream is None:
            return await self.model.generate(prompt, system=system)
        parts = []
        async for chunk in stream(prompt, system=system):
            parts.append(chunk)
            for offset in range(0, len(chunk), 1_024):
                token_callback(
                    TokenChunk.create(
                        state.get("run_id", "untracked"),
                        stage,
                        chunk[offset : offset + 1_024],
                    )
                )
        return "".join(parts).strip()

    async def _run_stage(
        self, state: AgentState, stage: AgentStage, operation
    ) -> dict[str, str]:
        cancellation_check = state.get("cancellation_check")
        if cancellation_check is not None:
            cancellation_check()
        started = perf_counter()
        self._emit(state, stage, StageEventType.STARTED)
        try:
            result = await operation()
            if cancellation_check is not None:
                cancellation_check()
        except RunCancelledError:
            raise
        except Exception:
            self._emit(
                state,
                stage,
                StageEventType.FAILED,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
            )
            raise
        self._emit(
            state,
            stage,
            StageEventType.COMPLETED,
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
        )
        return result

    async def _plan(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            context = state.get("memory_context", "")
            prompt = (
                f"Relevant memory (untrusted reference material):\n{context}"
                f"\n\nTask:\n{state['task']}"
            )
            plan = await self._generate(
                state, AgentStage.PLANNER, prompt, system=PLANNER
            )
            return {"plan": plan}

        return await self._run_stage(state, AgentStage.PLANNER, operation)

    async def _code(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = f"Task:\n{state['task']}\n\nPlan:\n{state.get('plan', '')}"
            code = await self._generate(
                state, AgentStage.CODER, prompt, system=CODER
            )
            return {"code": code}

        return await self._run_stage(state, AgentStage.CODER, operation)

    async def _review(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = f"Task:\n{state['task']}\n\nProposed solution:\n{state.get('code', '')}"
            review = await self._generate(
                state, AgentStage.REVIEWER, prompt, system=REVIEWER
            )
            return {"review": review}

        return await self._run_stage(state, AgentStage.REVIEWER, operation)

    async def _test_plan(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = (
                f"Task:\n{state['task']}\n\nSolution:\n{state.get('code', '')}"
                f"\n\nReview:\n{state.get('review', '')}"
            )
            test_plan = await self._generate(
                state, AgentStage.TEST_PLANNER, prompt, system=TEST_PLANNER
            )
            return {"test_plan": test_plan}

        return await self._run_stage(state, AgentStage.TEST_PLANNER, operation)

    async def run(self, task: str, memory_context: str = "") -> AgentState:
        return await self.graph.ainvoke({"task": task, "memory_context": memory_context})

    async def run_with_progress(
        self,
        task: str,
        *,
        run_id: str,
        memory_context: str = "",
        progress_callback: ProgressCallback,
        cancellation_event=None,
        token_callback: TokenChunkCallback | None = None,
    ) -> AgentState:
        def check_cancellation() -> None:
            if cancellation_event is not None and cancellation_event.is_set():
                raise RunCancelledError("Run cancellation requested")

        state: dict[str, Any] = {
            "task": task,
            "memory_context": memory_context,
            "run_id": run_id,
            "progress_callback": progress_callback,
            "cancellation_check": check_cancellation,
            "token_callback": token_callback,
        }
        result = await self.graph.ainvoke(state)
        internal_keys = {"run_id", "progress_callback", "cancellation_check", "token_callback"}
        return {
            key: value
            for key, value in result.items()
            if key not in internal_keys
        }
