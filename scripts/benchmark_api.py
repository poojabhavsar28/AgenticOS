"""Opt-in local API load probe for AgenticOS.

This measures HTTP latency and success rate; it is not a capacity certification.
Run only against an instance you own or are authorized to test.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx


def percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, (percent * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", choices=("health", "run"), default="health")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    host = (urlparse(args.base_url).hostname or "").lower()
    if not args.allow_remote and host not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("non-local targets require the explicit --allow-remote flag")
    if not 1 <= args.requests <= 10_000:
        parser.error("--requests must be between 1 and 10000")
    if not 1 <= args.concurrency <= 100:
        parser.error("--concurrency must be between 1 and 100")
    if args.concurrency > args.requests:
        parser.error("--concurrency cannot exceed --requests")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    url = args.base_url.rstrip("/") + ("/health" if args.mode == "health" else "/v1/runs")
    token = os.environ.get("AGENTICOS_BENCHMARK_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    latencies: list[float] = []
    failures: list[str] = []
    started = time.perf_counter()

    def request(index: int) -> tuple[float, int | None, str | None]:
        payload = (
            {"task": f"Benchmark smoke task {index}", "session_id": f"benchmark-{index}"}
            if args.mode == "run"
            else None
        )
        begin = time.perf_counter()
        try:
            with httpx.Client(timeout=args.timeout) as client:
                response = (
                    client.post(url, json=payload, headers=headers)
                    if payload is not None
                    else client.get(url, headers=headers)
                )
            elapsed = (time.perf_counter() - begin) * 1000
            return elapsed, response.status_code, None
        except httpx.HTTPError as exc:
            elapsed = (time.perf_counter() - begin) * 1000
            return elapsed, None, type(exc).__name__

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request, index) for index in range(args.requests)]
        for future in as_completed(futures):
            elapsed, status, error = future.result()
            latencies.append(elapsed)
            if error:
                failures.append(error)
            elif status is None or not 200 <= status < 300:
                failures.append(f"http_{status}")

    duration = time.perf_counter() - started
    successes = len(latencies) - len(failures)
    report = {
        "target": url,
        "mode": args.mode,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "successes": successes,
        "failures": len(failures),
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(successes / duration, 2) if duration else 0.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "failure_types": sorted({item for item in failures}),
        "note": (\n            "HTTP probe only; repeat with representative workloads before setting capacity limits."\n        ),
    }
    print(json.dumps(report, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
