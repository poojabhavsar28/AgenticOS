# Phase 6 — Testing, Evaluation, and Quality Gates

## Scope

- Deterministic evaluation contracts for named coding tasks.
- Structural checks for Planner, Coder, Reviewer, and Test Planner outputs.
- Configurable maximum output size and required-term checks.
- Per-case pass/fail results, score, and diagnostic issues.
- Aggregate pass rate and configurable quality threshold.
- An asynchronous suite runner that can evaluate any workflow implementation.
- CI runs the evaluation regression tests as a dedicated gate after the full test suite.

## Local commands

Run all tests and quality checks:

```bash
ruff check .
pytest -q
```

Run only the deterministic evaluation gate:

```bash
pytest -q tests/test_evaluation.py
```

The default evaluation cases cover a Python function, API input validation, and file-parser error handling. The suite runner accepts a workflow object, so tests use a deterministic fake workflow and do not require Ollama, model downloads, API keys, or network access.

## Scoring

Each case checks that all four workflow stages exist and contain non-empty text, that combined output stays within the configured size limit, and—when configured—that required terms appear in the combined output. The score is the fraction of checks passed. A case passes only when every check passes. The aggregate gate passes when the case pass rate meets the configured minimum.

## Limitations

This is a deterministic structural regression gate, not a semantic judge. Required-term matching does not prove correctness, security, factuality, or test quality. It does not execute generated code or validate that a proposed solution works. Model-based grading, benchmark datasets, golden patches, sandboxed execution, and performance evaluations are future work. CI deliberately does not download or invoke Ollama.

## Acceptance checks

- Empty or missing workflow stages fail evaluation.
- Oversized output fails evaluation.
- Required terms are checked case-insensitively.
- Pass-rate thresholds are validated and enforced.
- The suite runs against a fake workflow without Ollama or network access.
- The CI evaluation regression gate passes independently.
