"""Compare a current report against a baseline report.

Produces a structured diff: per-case status changes, latency deltas, and
side-by-side output diffs for cases whose output changed.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from .errors import SkillBenchError

DIFF_CONTEXT_LINES = 2
MAX_DIFF_LINES = 200


def _index_cases(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed = {}
    for case in report.get("cases", []):
        name = case.get("name")
        if isinstance(name, str):
            indexed[name] = case
    return indexed


def side_by_side_diff(before: str, after: str, width: int = 118) -> str:
    """Render a two-column diff ('<' baseline-only, '>' current-only, '*' both changed)."""
    left_lines = before.splitlines()
    right_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)

    col = max(20, (width - 7) // 2)

    def clip(line: str) -> str:
        line = line.replace("\t", "    ")
        return line if len(line) <= col else line[: col - 1] + "~"

    def emit_pairs(left_part, right_part, changed: bool) -> None:
        for k in range(max(len(left_part), len(right_part))):
            l = left_part[k] if k < len(left_part) else None
            r = right_part[k] if k < len(right_part) else None
            if not changed:
                marker = " "
            elif l is not None and r is not None:
                marker = "*"
            elif l is not None:
                marker = "<"
            else:
                marker = ">"
            rows.append(f"{marker} {clip(l or ''):<{col}} | {clip(r or '')}")

    rows: List[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            block_left = left_lines[i1:i2]
            block_right = right_lines[j1:j2]
            if len(block_left) > 2 * DIFF_CONTEXT_LINES + 1:
                emit_pairs(
                    block_left[:DIFF_CONTEXT_LINES], block_right[:DIFF_CONTEXT_LINES], False
                )
                rows.append(f"  {'...':<{col}} | ...")
                emit_pairs(
                    block_left[-DIFF_CONTEXT_LINES:], block_right[-DIFF_CONTEXT_LINES:], False
                )
            else:
                emit_pairs(block_left, block_right, False)
        else:
            left_part = left_lines[i1:i2] if tag in ("replace", "delete") else []
            right_part = right_lines[j1:j2] if tag in ("replace", "insert") else []
            emit_pairs(left_part, right_part, True)
        if len(rows) >= MAX_DIFF_LINES:
            rows.append("(diff truncated)")
            break
    return "\n".join(rows)


def compare_reports(
    baseline: Dict[str, Any],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    """Diff two report dicts (baseline = older, current = newer)."""
    base_cases = _index_cases(baseline)
    curr_cases = _index_cases(current)

    entries: List[Dict[str, Any]] = []
    regressions = improvements = changed = 0

    for name in sorted(set(base_cases) | set(curr_cases)):
        old = base_cases.get(name)
        new = curr_cases.get(name)
        if old is None:
            entries.append({"name": name, "change": "added", "status": new["status"]})
            continue
        if new is None:
            entries.append({"name": name, "change": "removed", "status": old["status"]})
            continue

        old_pass, new_pass = bool(old.get("passed")), bool(new.get("passed"))
        output_changed = old.get("output") != new.get("output")
        old_lat = old.get("latency_ms")
        new_lat = new.get("latency_ms")
        latency_delta = (
            (new_lat - old_lat)
            if isinstance(old_lat, (int, float)) and isinstance(new_lat, (int, float))
            else None
        )

        if not new_pass and old_pass:
            change = "regression"
            regressions += 1
        elif new_pass and not old_pass:
            change = "improvement"
            improvements += 1
        elif output_changed:
            change = "output_changed"
            changed += 1
        else:
            change = "unchanged"

        entry: Dict[str, Any] = {
            "name": name,
            "change": change,
            "status_before": old.get("status"),
            "status_after": new.get("status"),
            "latency_delta_ms": latency_delta,
        }
        if output_changed:
            entry["output_diff"] = side_by_side_diff(
                str(old.get("output") or ""), str(new.get("output") or "")
            )
        entries.append(entry)

    base_summary = baseline.get("summary") or {}
    curr_summary = current.get("summary") or {}
    comparison = {
        "baseline_suite": baseline.get("suite"),
        "current_suite": current.get("suite"),
        "regressions": regressions,
        "improvements": improvements,
        "output_changed": changed,
        "pass_rate_before": base_summary.get("pass_rate"),
        "pass_rate_after": curr_summary.get("pass_rate"),
        "cases": entries,
    }
    return comparison


def format_comparison(comparison: Dict[str, Any]) -> str:
    """Human-readable rendering of a comparison dict."""
    lines = []
    lines.append(
        f"Comparing baseline suite '{comparison.get('baseline_suite')}' "
        f"vs current suite '{comparison.get('current_suite')}'"
    )
    before = comparison.get("pass_rate_before")
    after = comparison.get("pass_rate_after")
    if before is not None and after is not None:
        lines.append(f"Pass rate: {before:.0%} -> {after:.0%}")
    lines.append(
        f"Regressions: {comparison['regressions']}  "
        f"Improvements: {comparison['improvements']}  "
        f"Output changed (still same status): {comparison['output_changed']}"
    )
    interesting = [
        c
        for c in comparison["cases"]
        if c["change"] not in ("unchanged",)
    ]
    if not interesting:
        lines.append("No case-level changes.")
        return "\n".join(lines)

    for entry in interesting:
        name = entry["name"]
        change = entry["change"]
        if change in ("added", "removed"):
            lines.append(f"\n[{change}] {name}")
            continue
        lat = entry.get("latency_delta_ms")
        lat_note = (
            f" ({lat:+.0f} ms)"
            if isinstance(lat, (int, float)) and abs(lat) >= 0.5
            else ""
        )
        lines.append(
            f"\n[{change}] {name}: "
            f"{entry.get('status_before')} -> {entry.get('status_after')}{lat_note}"
        )
        diff = entry.get("output_diff")
        if diff:
            lines.append("  baseline < | > current")
            lines.extend("  " + row for row in diff.splitlines())
    return "\n".join(lines)


def compare_report_files(baseline_path: str, current_path: str) -> Dict[str, Any]:
    from .runner import load_report  # local import to avoid a cycle

    baseline = load_report(baseline_path)
    current = load_report(current_path)
    if baseline.get("suite") != current.get("suite"):
        raise SkillBenchError(
            f"Suite mismatch: baseline is '{baseline.get('suite')}', "
            f"current is '{current.get('suite')}'"
        )
    return compare_reports(baseline, current)
