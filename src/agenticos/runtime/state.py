"""State shared by nodes in the coding workflow."""

from collections.abc import Callable
from typing import TypedDict

from agenticos.runtime.progress import ProgressCallback, TokenChunkCallback


class AgentState(TypedDict, total=False):
    task: str
    memory_context: str
    plan: str
    code: str
    review: str
    test_plan: str
    run_id: str
    progress_callback: ProgressCallback
    token_callback: TokenChunkCallback
    cancellation_check: Callable[[], None]
