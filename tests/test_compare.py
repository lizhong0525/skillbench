import unittest

from skillbench.compare import (
    compare_reports,
    format_comparison,
    side_by_side_diff,
)
from skillbench.errors import SkillBenchError


def make_report(suite, cases):
    passed = sum(1 for c in cases if c["passed"])
    return {
        "suite": suite,
        "summary": {
            "total": len(cases),
            "passed": passed,
            "pass_rate": passed / len(cases) if cases else 0.0,
        },
        "cases": cases,
    }


def case(name, passed, output, status=None, latency=10.0):
    return {
        "name": name,
        "passed": passed,
        "status": status or ("pass" if passed else "fail"),
        "output": output,
        "latency_ms": latency,
    }


class TestCompare(unittest.TestCase):
    def test_regression_and_improvement_detection(self):
        baseline = make_report(
            "s",
            [
                case("ok-stays", True, "same"),
                case("breaks", True, "old output"),
                case("heals", False, "old"),
            ],
        )
        current = make_report(
            "s",
            [
                case("ok-stays", True, "same"),
                case("breaks", False, "new output"),
                case("heals", True, "new", latency=25.0),
                case("brand-new", True, "hi"),
            ],
        )
        cmp = compare_reports(baseline, current)
        self.assertEqual(cmp["regressions"], 1)
        self.assertEqual(cmp["improvements"], 1)
        changes = {c["name"]: c["change"] for c in cmp["cases"]}
        self.assertEqual(changes["breaks"], "regression")
        self.assertEqual(changes["heals"], "improvement")
        self.assertEqual(changes["ok-stays"], "unchanged")
        self.assertEqual(changes["brand-new"], "added")
        heals = next(c for c in cmp["cases"] if c["name"] == "heals")
        self.assertAlmostEqual(heals["latency_delta_ms"], 15.0)

    def test_output_changed_same_status(self):
        baseline = make_report("s", [case("c", True, "v1 text")])
        current = make_report("s", [case("c", True, "v2 text")])
        cmp = compare_reports(baseline, current)
        self.assertEqual(cmp["output_changed"], 1)
        entry = cmp["cases"][0]
        self.assertEqual(entry["change"], "output_changed")
        self.assertIn("v1 text", entry["output_diff"])
        self.assertIn("v2 text", entry["output_diff"])

    def test_removed_case(self):
        baseline = make_report("s", [case("gone", True, "x")])
        current = make_report("s", [case("other", True, "y")])
        cmp = compare_reports(baseline, current)
        changes = {c["name"]: c["change"] for c in cmp["cases"]}
        self.assertEqual(changes["gone"], "removed")
        self.assertEqual(changes["other"], "added")

    def test_no_changes(self):
        report = make_report("s", [case("c", True, "same")])
        cmp = compare_reports(report, report)
        text = format_comparison(cmp)
        self.assertIn("No case-level changes", text)

    def test_format_includes_diff_markers(self):
        baseline = make_report("s", [case("c", True, "line one\nline two")])
        current = make_report("s", [case("c", False, "line one\nline CHANGED")])
        text = format_comparison(compare_reports(baseline, current))
        self.assertIn("[regression] c", text)
        self.assertIn("line CHANGED", text)


class TestSideBySideDiff(unittest.TestCase):
    def test_identical(self):
        out = side_by_side_diff("a\nb", "a\nb")
        self.assertIn("a", out)
        self.assertNotIn("<", out.replace(" | ", ""))

    def test_change_has_markers(self):
        out = side_by_side_diff("old", "new")
        self.assertIn("*", out)  # both columns changed
        self.assertIn("old", out)
        self.assertIn("new", out)
        added_only = side_by_side_diff("", "new line")
        self.assertIn(">", added_only)  # current-only line

    def test_empty_inputs(self):
        self.assertIsInstance(side_by_side_diff("", ""), str)
        out = side_by_side_diff("", "new line")
        self.assertIn("new line", out)


class TestCompareFilesSuiteMismatch(unittest.TestCase):
    def test_mismatch_raises(self):
        import json
        import tempfile

        from skillbench.compare import compare_report_files

        with tempfile.TemporaryDirectory() as tmp:
            import os

            p1 = os.path.join(tmp, "a.json")
            p2 = os.path.join(tmp, "b.json")
            with open(p1, "w", encoding="utf-8") as fh:
                json.dump(make_report("suite-a", [case("c", True, "x")]), fh)
            with open(p2, "w", encoding="utf-8") as fh:
                json.dump(make_report("suite-b", [case("c", True, "x")]), fh)
            with self.assertRaisesRegex(SkillBenchError, "Suite mismatch"):
                compare_report_files(p1, p2)


if __name__ == "__main__":
    unittest.main()
