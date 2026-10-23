import json
import os
import tempfile
import unittest

from skillbench.adapters import MockAdapter, ModelAdapter, ModelResponse
from skillbench.errors import AdapterError, SkillBenchError
from skillbench.runner import load_report, run_suite, write_report
from skillbench.suite import load_suite

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class ExplodingAdapter(ModelAdapter):
    name = "exploding"

    def complete(self, prompt, messages=None):
        raise AdapterError("boom")


class TestRunSuite(unittest.TestCase):
    def test_pass_and_fail_counts(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.json"))
        report = run_suite(suite, MockAdapter(suite.model))
        summary = report["summary"]
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertAlmostEqual(summary["pass_rate"], 0.5)
        self.assertIsNotNone(summary["total_tokens"])
        self.assertIsNotNone(summary["latency_ms"]["mean"])

        failing = next(c for c in report["cases"] if c["name"] == "bob fails")
        self.assertEqual(failing["status"], "fail")
        self.assertFalse(failing["assertions"][0]["passed"])
        self.assertIn("Carol", failing["assertions"][0]["message"])

    def test_adapter_error_marks_case_as_error_not_silent(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.json"))
        report = run_suite(suite, ExplodingAdapter(suite.model))
        self.assertEqual(report["summary"]["errors"], 2)
        for case in report["cases"]:
            self.assertEqual(case["status"], "error")
            self.assertIn("boom", case["error"])

    def test_determinism(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.json"))
        r1 = run_suite(suite, MockAdapter(suite.model))
        r2 = run_suite(suite, MockAdapter(suite.model))
        outputs1 = [c["output"] for c in r1["cases"]]
        outputs2 = [c["output"] for c in r2["cases"]]
        self.assertEqual(outputs1, outputs2)


class TestReportIO(unittest.TestCase):
    def test_round_trip(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.json"))
        report = run_suite(suite, MockAdapter(suite.model))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "report.json")
            write_report(report, path)
            loaded = load_report(path)
        self.assertEqual(loaded["suite"], report["suite"])
        self.assertEqual(len(loaded["cases"]), 2)

    def test_load_report_missing(self):
        with self.assertRaises(SkillBenchError):
            load_report("/no/such/report.json")

    def test_load_report_malformed(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{broken")
            path = fh.name
        try:
            with self.assertRaisesRegex(SkillBenchError, "Malformed"):
                load_report(path)
        finally:
            os.unlink(path)

    def test_load_report_wrong_shape(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"hello": "world"}, fh)
            path = fh.name
        try:
            with self.assertRaisesRegex(SkillBenchError, "not a SkillBench report"):
                load_report(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
