"""Run a suite against an adapter and build a JSON-serializable report."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .adapters import ModelAdapter
from .assertions import check_assertion
from .errors import AdapterError, SkillBenchError, SuiteLoadError
from .suite import Suite, render_prompt

REPORT_SCHEMA_VERSION = 1


def run_suite(
    suite: Suite,
    adapter: ModelAdapter,
    on_progress=None,
) -> Dict[str, Any]:
    """Execute every case and return a report dict.

    A case that fails to produce a model response (adapter error, template
    error) is recorded as an errored case, not silently skipped; the suite
    summary counts it as failed.
    """
    started = time.perf_counter()
    case_results: List[Dict[str, Any]] = []

    for case in suite.cases:
        if on_progress:
            on_progress(case.name)
        error: Optional[str] = None
        output = ""
        latency_ms: Optional[float] = None
        prompt_tokens = completion_tokens = total_tokens = None

        try:
            prompt = render_prompt(suite.prompt_template, case.input)
            t0 = time.perf_counter()
            response = adapter.complete(prompt)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            output = response.text
            prompt_tokens = response.prompt_tokens
            completion_tokens = response.completion_tokens
            total_tokens = response.total_tokens
        except (AdapterError, SuiteLoadError) as exc:
            error = str(exc)

        assertion_results = []
        if error is None:
            for spec in case.assertions:
                assertion_results.append(
                    check_assertion(spec, output, latency_ms, completion_tokens)
                )

        passed = error is None and all(r.passed for r in assertion_results)
        case_results.append(
            {
                "name": case.name,
                "status": "error" if error else ("pass" if passed else "fail"),
                "passed": passed,
                "error": error,
                "output": output,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "assertions": [
                    {"type": r.type, "passed": r.passed, "message": r.message}
                    for r in assertion_results
                ],
            }
        )

    total = len(case_results)
    passed_count = sum(1 for c in case_results if c["passed"])
    error_count = sum(1 for c in case_results if c["status"] == "error")
    latencies = [c["latency_ms"] for c in case_results if c["latency_ms"] is not None]
    total_tokens_values = [
        c["total_tokens"] for c in case_results if c["total_tokens"] is not None
    ]
    wall_ms = (time.perf_counter() - started) * 1000.0

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite": suite.name,
        "suite_version": suite.version,
        "suite_path": suite.source_path,
        "prompt_path": suite.prompt_path,
        "adapter": adapter.name,
        "generated_at_epoch": time.time(),
        "summary": {
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count - error_count,
            "errors": error_count,
            "pass_rate": (passed_count / total) if total else 0.0,
            "latency_ms": {
                "min": min(latencies) if latencies else None,
                "max": max(latencies) if latencies else None,
                "mean": (sum(latencies) / len(latencies)) if latencies else None,
                "wall": wall_ms,
            },
            "total_tokens": sum(total_tokens_values) if total_tokens_values else None,
            # Human review is opt-in: mark case names needing a human look.
            "human_review": [],
        },
        "cases": case_results,
    }


def write_report(report: Dict[str, Any], path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        raise SkillBenchError(f"Cannot write report to {path}: {exc}") from exc


def load_report(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise SkillBenchError(f"Report file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SkillBenchError(f"Malformed JSON report {path}: {exc}") from exc
    except OSError as exc:
        raise SkillBenchError(f"Cannot read report {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise SkillBenchError(
            f"{path} is not a SkillBench report (missing 'cases' list)"
        )
    return data
