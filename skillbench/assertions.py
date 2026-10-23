"""Explicit assertion checks applied to model outputs.

Supported assertion types:
  contains / not_contains   substring checks on the output text
  equals                    exact match (after str() coercion)
  starts_with / ends_with   prefix/suffix checks
  regex                     ``re.search`` pattern match
  json_valid                output parses as JSON
  max_latency_ms            case latency must be <= value (needs runner timing)
  max_completion_tokens     completion token count must be <= value (needs usage)

Assertions never judge "semantic quality" from a score — they are explicit,
deterministic checks. Use the human-review workflow in the report for
everything they cannot express.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from .suite import AssertionSpec


@dataclass
class AssertionResult:
    type: str
    passed: bool
    message: str


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def check_assertion(
    spec: AssertionSpec,
    output: str,
    latency_ms: Optional[float] = None,
    completion_tokens: Optional[int] = None,
) -> AssertionResult:
    """Evaluate one assertion; unknown types fail loudly rather than passing."""
    t = spec.type
    value = spec.value

    if t == "contains":
        needle = _as_str(value)
        ok = needle in output
        return AssertionResult(t, ok, f"expected output to contain {needle!r}")

    if t == "not_contains":
        needle = _as_str(value)
        ok = needle not in output
        return AssertionResult(t, ok, f"expected output NOT to contain {needle!r}")

    if t == "equals":
        expected = _as_str(value)
        ok = output == expected
        return AssertionResult(t, ok, f"expected output to equal {expected!r}")

    if t == "starts_with":
        prefix = _as_str(value)
        ok = output.startswith(prefix)
        return AssertionResult(t, ok, f"expected output to start with {prefix!r}")

    if t == "ends_with":
        suffix = _as_str(value)
        ok = output.endswith(suffix)
        return AssertionResult(t, ok, f"expected output to end with {suffix!r}")

    if t == "regex":
        pattern = _as_str(value)
        try:
            ok = re.search(pattern, output, re.DOTALL) is not None
        except re.error as exc:
            return AssertionResult(t, False, f"invalid regex {pattern!r}: {exc}")
        return AssertionResult(t, ok, f"expected output to match /{pattern}/")

    if t == "json_valid":
        try:
            json.loads(output)
            ok = True
        except json.JSONDecodeError:
            ok = False
        return AssertionResult(t, ok, "expected output to be valid JSON")

    if t == "max_latency_ms":
        if latency_ms is None:
            return AssertionResult(t, False, "latency unavailable for max_latency_ms")
        try:
            limit = float(value)
        except (TypeError, ValueError):
            return AssertionResult(t, False, f"max_latency_ms value {value!r} is not a number")
        ok = latency_ms <= limit
        return AssertionResult(t, ok, f"latency {latency_ms:.1f} ms vs limit {limit:g} ms")

    if t == "max_completion_tokens":
        if completion_tokens is None:
            return AssertionResult(
                t, False, "token usage unavailable for max_completion_tokens"
            )
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return AssertionResult(
                t, False, f"max_completion_tokens value {value!r} is not an integer"
            )
        ok = completion_tokens <= limit
        return AssertionResult(
            t, ok, f"completion tokens {completion_tokens} vs limit {limit}"
        )

    return AssertionResult(
        t, False, f"unknown assertion type '{t}' (fails closed, fix the suite)"
    )
