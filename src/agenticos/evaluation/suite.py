"""Run a deterministic evaluation suite against a workflow implementation."""

from typing import Any, Protocol

from agenticos.evaluation.models import EvaluationCase, EvaluationResult
from agenticos.evaluation.scoring import evaluate_output, summarize_results


class EvaluatableWorkflow(Protocol):
    async def run(self, task: str, memory_context: str = "") -> dict[str, Any]:
        """Execute a workflow for evaluation."""


DEFAULT_CASES = (
    EvaluationCase(
        case_id="python-function",
        task="Plan and implement a Python function with tests.",
        required_terms=("function", "test"),
    ),
    EvaluationCase(
        case_id="input-validation",
        task="Design input validation for a JSON API.",
        required_terms=("validation", "input"),
    ),
    EvaluationCase(
        case_id="error-handling",
        task="Implement robust error handling for a file parser.",
        required_terms=("error", "file"),
    ),
)


async def run_evaluation_suite(
    workflow: EvaluatableWorkflow,
    cases: tuple[EvaluationCase, ...] = DEFAULT_CASES,
    *,
    minimum_pass_rate: float = 1.0,
) -> tuple[tuple[EvaluationResult, ...], dict[str, Any]]:
    if not cases:
        raise ValueError("At least one evaluation case is required")
    results: list[EvaluationResult] = []
    for case in cases:
        output = await workflow.run(case.task, memory_context="")
        results.append(evaluate_output(case, output))
    result_tuple = tuple(results)
    return result_tuple, summarize_results(
        result_tuple, minimum_pass_rate=minimum_pass_rate
    )
