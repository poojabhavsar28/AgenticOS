"""State shared by nodes in the coding workflow."""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    task: str
    memory_context: str
    plan: str
    code: str
    review: str
    test_plan: str
