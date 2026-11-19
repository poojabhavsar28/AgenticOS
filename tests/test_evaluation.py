"""Tests for deterministic workflow evaluation and regression gates."""

import pytest

from agenticos.evaluation import (
    DEFAULT_CASES,
    EvaluationCase,
    evaluate_output,
    run_evaluation_suite,
    summarize_results,
)


def complete_output() -> dict[str, str]:
    return {
        "plan": "Plan the function and validation approach.",
        "code": "Implement the function with input validation and error handling.",
        "review": "Review the function for correctness and error cases.",
        "test_plan": "Add a test for valid input and invalid input.",
    }


def test_evaluator_accepts_complete_output_and_required_terms() -> None:
    case = EvaluationCase(
        "valid-output",
        "Build a function",
        required_terms=("function", "validation", "test"),
    )

    result = evaluate_output(case, complete_output())

    assert result.passed is True
    assert result.score == 1.0
    assert all(result.checks.values())
    assert result.issues == ()


def test_evaluator_rejects_missing_stage() -> None:
    output = complete_output()
    output["review"] = ""

    result = evaluate_output(EvaluationCase("missing-review", "Build"), output)

    assert result.passed is False
    assert result.checks["review_present"] is False
    assert "Missing or empty workflow stage: review" in result.issues


def test_evaluator_rejects_oversized_and_missing_required_terms() -> None:
    case = EvaluationCase(
        "bounded-output",
        "Build",
        required_terms=("database",),
        max_output_chars=20,
    )

    result = evaluate_output(case, complete_output())

    assert result.passed is False
    assert result.checks["output_within_limit"] is False
    assert result.checks["required_terms_present"] is False


def test_summary_enforces_pass_rate_threshold() -> None:
    good = evaluate_output(EvaluationCase("good", "Build"), complete_output())
    bad = evaluate_output(EvaluationCase("bad", "Build"), {})

    summary = summarize_results([good, bad], minimum_pass_rate=0.75)

    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["gate_passed"] is False


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_summary_rejects_invalid_threshold(threshold: float) -> None:
    result = evaluate_output(EvaluationCase("good", "Build"), complete_output())
    with pytest.raises(ValueError, match="between 0 and 1"):
        summarize_results([result], minimum_pass_rate=threshold)


@pytest.mark.asyncio
async def test_suite_runs_without_ollama_or_network() -> None:
    class DeterministicWorkflow:
        async def run(self, task: str, memory_context: str = "") -> dict[str, str]:
            assert task
            assert memory_context == ""
            return {
                "plan": "Plan function validation and test cases.",
                "code": "Implement input validation and file error handling function.",
                "review": "Review error handling and function behavior.",
                "test_plan": "Test input validation, file errors, and function output.",
            }

    results, summary = await run_evaluation_suite(
        DeterministicWorkflow(), DEFAULT_CASES, minimum_pass_rate=1.0
    )

    assert len(results) == len(DEFAULT_CASES)
    assert summary["gate_passed"] is True
    assert summary["pass_rate"] == 1.0


@pytest.mark.asyncio
async def test_suite_rejects_empty_case_collection() -> None:
    class UnusedWorkflow:
        async def run(self, task: str, memory_context: str = "") -> dict[str, str]:
            raise AssertionError("Workflow should not be called")

    with pytest.raises(ValueError, match="At least one"):
        await run_evaluation_suite(UnusedWorkflow(), ())
