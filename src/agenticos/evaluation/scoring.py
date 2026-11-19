"""Deterministic checks for the four-stage coding workflow."""

from collections.abc import Mapping
from typing import Any

from agenticos.evaluation.models import EvaluationCase, EvaluationResult

REQUIRED_STAGES = ("plan", "code", "review", "test_plan")


def evaluate_output(
    case: EvaluationCase,
    output: Mapping[str, Any],
) -> EvaluationResult:
    """Score structural quality without requiring a live model or network."""
    checks: dict[str, bool] = {}
    issues: list[str] = []
    combined_parts: list[str] = []

    for stage in REQUIRED_STAGES:
        value = output.get(stage)
        valid = isinstance(value, str) and bool(value.strip())
        checks[f"{stage}_present"] = valid
        if not valid:
            issues.append(f"Missing or empty workflow stage: {stage}")
        elif isinstance(value, str):
            combined_parts.append(value)

    combined = "\n".join(combined_parts)
    checks["output_within_limit"] = len(combined) <= case.max_output_chars
    if not checks["output_within_limit"]:
        issues.append("Combined stage output exceeds the configured character limit")

    if case.required_terms:
        lowered = combined.casefold()
        missing_terms = [
            term for term in case.required_terms if term.casefold() not in lowered
        ]
        checks["required_terms_present"] = not missing_terms
        if missing_terms:
            issues.append("Missing required terms: " + ", ".join(missing_terms))

    score = sum(checks.values()) / len(checks) if checks else 0.0
    return EvaluationResult(
        case_id=case.case_id,
        passed=all(checks.values()),
        score=score,
        checks=checks,
        issues=tuple(issues),
    )


def summarize_results(
    results: tuple[EvaluationResult, ...] | list[EvaluationResult],
    *,
    minimum_pass_rate: float = 1.0,
) -> dict[str, Any]:
    if not 0.0 <= minimum_pass_rate <= 1.0:
        raise ValueError("Minimum pass rate must be between 0 and 1")
    if not results:
        raise ValueError("At least one evaluation result is required")
    passed = sum(result.passed for result in results)
    pass_rate = passed / len(results)
    average_score = sum(result.score for result in results) / len(results)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": pass_rate,
        "average_score": average_score,
        "gate_passed": pass_rate >= minimum_pass_rate,
    }
