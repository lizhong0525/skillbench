"""Command-line interface for SkillBench."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .adapters import create_adapter
from .compare import compare_report_files, format_comparison
from .errors import SkillBenchError
from .runner import load_report, run_suite, write_report
from .suite import load_suite


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillbench",
        description="Regression testing for prompts and agent skills.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a test suite and print/save a report")
    run_p.add_argument("suite", help="path to a .yaml/.yml or .json suite file")
    run_p.add_argument(
        "--adapter",
        choices=["mock", "openai"],
        default=None,
        help="override the adapter named in the suite (default: suite setting or mock)",
    )
    run_p.add_argument(
        "--report", "-o", default=None, help="write the JSON report to this path"
    )
    run_p.add_argument(
        "--baseline",
        default=None,
        help="compare against a baseline JSON report after running",
    )

    cmp_p = sub.add_parser(
        "compare", help="compare a current report against a baseline report"
    )
    cmp_p.add_argument("baseline", help="baseline JSON report (older)")
    cmp_p.add_argument("current", help="current JSON report (newer)")

    return parser


def _print_report_summary(report: dict) -> None:
    summary = report["summary"]
    print(f"Suite: {report['suite']} (adapter: {report['adapter']})")
    print(
        f"Cases: {summary['total']}  passed: {summary['passed']}  "
        f"failed: {summary['failed']}  errors: {summary['errors']}  "
        f"pass rate: {summary['pass_rate']:.0%}"
    )
    lat = summary["latency_ms"]
    if lat["mean"] is not None:
        print(
            f"Latency ms: min {lat['min']:.1f}  mean {lat['mean']:.1f}  "
            f"max {lat['max']:.1f}  (wall {lat['wall']:.1f})"
        )
    if summary["total_tokens"] is not None:
        print(f"Total tokens (reported/estimated): {summary['total_tokens']}")

    for case in report["cases"]:
        mark = {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}[case["status"]]
        lat_note = (
            f" [{case['latency_ms']:.0f} ms]"
            if isinstance(case.get("latency_ms"), (int, float))
            else ""
        )
        print(f"  {mark:5} {case['name']}{lat_note}")
        if case["error"]:
            print(f"        error: {case['error']}")
        for result in case["assertions"]:
            if not result["passed"]:
                print(f"        x {result['type']}: {result['message']}")


def _cmd_run(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    adapter_name = args.adapter or suite.model.get("adapter") or "mock"
    adapter = create_adapter(adapter_name, suite.model)

    report = run_suite(suite, adapter)
    _print_report_summary(report)

    if args.report:
        write_report(report, args.report)
        print(f"Report written to {args.report}")

    if args.baseline:
        comparison = compare_report_files(args.baseline, _report_path_or_inline(args, report))
        print()
        print(format_comparison(comparison))
        return 1 if comparison["regressions"] > 0 else _exit_code(report)

    return _exit_code(report)


def _report_path_or_inline(args: argparse.Namespace, report: dict):
    if args.report:
        return args.report
    # No --report given: keep compare pure in-memory by round-tripping through
    # the same shape load_report validates.
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(report, tmp)
    finally:
        tmp.close()
    return tmp.name


def _exit_code(report: dict) -> int:
    summary = report["summary"]
    if summary["errors"] > 0:
        return 2
    return 0 if summary["failed"] == 0 else 1


def _cmd_compare(args: argparse.Namespace) -> int:
    comparison = compare_report_files(args.baseline, args.current)
    print(format_comparison(comparison))
    return 1 if comparison["regressions"] > 0 else 0


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles often default to GBK/cp1252; never crash printing output
    # that contains characters outside the console code page.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "compare":
            return _cmd_compare(args)
    except SkillBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command}")  # unreachable
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
