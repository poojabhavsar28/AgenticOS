"""Sequential LangGraph workflow for coding tasks."""

import asyncio
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from agenticos.inference.base import ModelClient
from agenticos.runtime.progress import (
    AgentStage,
    ProgressCallback,
    StageEventType,
    StageProgress,
    RunCancelledError,
)
from agenticos.runtime.prompts import CODER, PLANNER, REVIEWER, TEST_PLANNER
from agenticos.runtime.state import AgentState


class CodingWorkflow:
    def __init__(self, model: ModelClient) -> None:
        self.model = model
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

    async def _run_stage(
        self, state: AgentState, stage: AgentStage, operation
    ) -> dict[str, str]:
        cancellation_event = state.get("cancellation_event")
        if cancellation_event is not None and cancellation_event.is_set():
            raise RunCancelledError("Run cancellation requested")
        started = perf_counter()
        self._emit(state, stage, StageEventType.STARTED)
        try:
            result = await operation()
            if cancellation_event is not None and cancellation_event.is_set():
                raise RunCancelledError("Run cancellation requested")
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
            return {"plan": await self.model.generate(prompt, system=PLANNER)}

        return await self._run_stage(state, AgentStage.PLANNER, operation)

    async def _code(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = f"Task:\n{state['task']}\n\nPlan:\n{state.get('plan', '')}"
            return {"code": await self.model.generate(prompt, system=CODER)}

        return await self._run_stage(state, AgentStage.CODER, operation)

    async def _review(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = f"Task:\n{state['task']}\n\nProposed solution:\n{state.get('code', '')}"
            return {"review": await self.model.generate(prompt, system=REVIEWER)}

        return await self._run_stage(state, AgentStage.REVIEWER, operation)

    async def _test_plan(self, state: AgentState) -> dict[str, str]:
        async def operation() -> dict[str, str]:
            prompt = (
                f"Task:\n{state['task']}\n\nSolution:\n{state.get('code', '')}"
                f"\n\nReview:\n{state.get('review', '')}"
            )
            return {"test_plan": await self.model.generate(prompt, system=TEST_PLANNER)}

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
        cancellation_event: asyncio.Event | None = None,
    ) -> AgentState:
        state: dict[str, Any] = {
            "task": task,
            "memory_context": memory_context,
            "run_id": run_id,
            "progress_callback": progress_callback,
            "cancellation_event": cancellation_event,
        }
        return await self.graph.ainvoke(state)
