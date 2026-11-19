"""Sequential LangGraph workflow for coding tasks."""

from langgraph.graph import END, START, StateGraph

from agenticos.inference.base import ModelClient
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

    async def _plan(self, state: AgentState) -> dict[str, str]:
        return {"plan": await self.model.generate(state["task"], system=PLANNER)}

    async def _code(self, state: AgentState) -> dict[str, str]:
        prompt = f"Task:\n{state['task']}\n\nPlan:\n{state.get('plan', '')}"
        return {"code": await self.model.generate(prompt, system=CODER)}

    async def _review(self, state: AgentState) -> dict[str, str]:
        prompt = f"Task:\n{state['task']}\n\nProposed solution:\n{state.get('code', '')}"
        return {"review": await self.model.generate(prompt, system=REVIEWER)}

    async def _test_plan(self, state: AgentState) -> dict[str, str]:
        prompt = f"Task:\n{state['task']}\n\nSolution:\n{state.get('code', '')}\n\nReview:\n{state.get('review', '')}"
        return {"test_plan": await self.model.generate(prompt, system=TEST_PLANNER)}

    async def run(self, task: str) -> AgentState:
        return await self.graph.ainvoke({"task": task})
