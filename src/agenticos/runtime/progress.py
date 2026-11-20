"""Typed, payload-safe progress contracts for agent workflow stages."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Callable


class AgentStage(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TEST_PLANNER = "test_planner"


class StageEventType(StrEnum):
    STARTED = "stage_started"
    COMPLETED = "stage_completed"
    FAILED = "stage_failed"


@dataclass(frozen=True)
class StageProgress:
    """Operational stage metadata; never contains prompts or model output."""

    run_id: str
    stage: AgentStage
    event_type: StageEventType
    occurred_at: str
    duration_ms: int | None = None

    @classmethod
    def create(
        cls,
        run_id: str,
        stage: AgentStage,
        event_type: StageEventType,
        *,
        duration_ms: int | None = None,
    ) -> "StageProgress":
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        return cls(
            run_id=run_id,
            stage=stage,
            event_type=event_type,
            occurred_at=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
        )


ProgressCallback = Callable[[StageProgress], None]
