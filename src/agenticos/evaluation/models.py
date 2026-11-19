"""Deterministic workflow-output evaluation contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    task: str
    required_terms: tuple[str, ...] = ()
    max_output_chars: int = 20_000

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.task.strip():
            raise ValueError("Evaluation case ID and task are required")
        if self.max_output_chars < 1:
            raise ValueError("Maximum output size must be positive")
        if any(not term.strip() for term in self.required_terms):
            raise ValueError("Required terms cannot contain empty values")


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    score: float
    checks: dict[str, bool]
    issues: tuple[str, ...]
