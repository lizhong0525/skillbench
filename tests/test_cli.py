import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from skillbench.cli import main

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCliRun(unittest.TestCase):
    def test_run_prints_summary_and_exit_1_on_failure(self):
        code, out, _ = run_cli(
            ["run", os.path.join(FIXTURES, "greeter_suite.json")]
        )
        self.assertEqual(code, 1)  # one case fails by fixture design
        self.assertIn("pass rate: 50%", out)
        self.assertIn("PASS", out)
        self.assertIn("FAIL", out)
        self.assertIn("Total tokens", out)

    def test_run_writes_report_and_compares_to_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline.json")
            current = os.path.join(tmp, "current.json")
            suite = os.path.join(FIXTURES, "greeter_suite.json")

            code1, _, _ = run_cli(["run", suite, "-o", baseline])
            self.assertEqual(code1, 1)
            code2, out2, _ = run_cli(
                ["run", suite, "-o", current, "--baseline", baseline]
            )
            self.assertEqual(code2, 1)  # failures persist, no regressions
            self.assertIn("No case-level changes", out2)

            with open(baseline, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["suite"], "greeter-suite")

    def test_run_bad_suite_exit_2(self):
        code, _, err = run_cli(["run", "/no/such/suite.yaml"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_run_openai_adapter_without_key_errors(self):
        # Clear any real credentials: the openai adapter must fail fast with a
        # config error instead of ever touching the network in tests.
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("SKILLBENCH_") and not k.startswith("OPENAI_")
        }
        from unittest import mock as umock

        with umock.patch.dict("os.environ", clean_env, clear=True):
            code, _, err = run_cli(
                ["run", os.path.join(FIXTURES, "greeter_suite.json"), "--adapter", "openai"]
            )
        self.assertEqual(code, 2)
        self.assertIn("SKILLBENCH_API_KEY", err)

    def test_run_baseline_without_report_path(self):
        # --baseline without -o must compare in memory, not via a temp file.
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline.json")
            suite = os.path.join(FIXTURES, "greeter_suite.json")
            run_cli(["run", suite, "-o", baseline])

            import glob

            pattern = os.path.join(tempfile.gettempdir(), "*.json")
            before = set(glob.glob(pattern))
            code, out, _ = run_cli(["run", suite, "--baseline", baseline])
            after = set(glob.glob(pattern))
            self.assertEqual(code, 1)  # failures persist, no regressions
            self.assertIn("No case-level changes", out)
            self.assertEqual(before, after)  # no leaked temp report files

    def test_run_unknown_adapter_exit_2(self):
        code, _, err = run_cli(
            ["run", os.path.join(FIXTURES, "greeter_suite.json"), "--adapter", "nope"]
        )
        self.assertEqual(code, 2)
        self.assertIn("Unknown adapter 'nope'", err)

    def test_run_custom_registered_adapter(self):
        # README promises adapters registered in skillbench.adapters._REGISTRY
        # are selectable via --adapter.
        from skillbench import adapters

        class DummyAdapter(adapters.ModelAdapter):
            name = "dummy-grill"

            def complete(self, prompt, messages=None):
                return adapters.ModelResponse(text="dummy reply")

        adapters._REGISTRY[DummyAdapter.name] = DummyAdapter
        try:
            code, out, _ = run_cli(
                [
                    "run",
                    os.path.join(FIXTURES, "greeter_suite.json"),
                    "--adapter",
                    DummyAdapter.name,
                ]
            )
        finally:
            del adapters._REGISTRY[DummyAdapter.name]
        self.assertIn("(adapter: dummy-grill)", out)
        self.assertIn(code, (0, 1))  # assertions decide, not the CLI

    def test_compare_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline.json")
            current = os.path.join(tmp, "current.json")
            suite = os.path.join(FIXTURES, "greeter_suite.json")
            run_cli(["run", suite, "-o", baseline])
            run_cli(["run", suite, "-o", current])
            code, out, _ = run_cli(["compare", baseline, current])
            self.assertEqual(code, 0)
            self.assertIn("Pass rate:", out)

    def test_compare_regression_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline.json")
            current = os.path.join(tmp, "current.json")
            run_cli(["run", os.path.join(FIXTURES, "greeter_suite.json"), "-o", baseline])

            # Craft a "current" report where the passing case now fails.
            with open(baseline, encoding="utf-8") as fh:
                data = json.load(fh)
            for c in data["cases"]:
                c["passed"] = False
                c["status"] = "fail"
                c["output"] = "something else entirely"
            data["summary"]["passed"] = 0
            data["summary"]["pass_rate"] = 0.0
            with open(current, "w", encoding="utf-8") as fh:
                json.dump(data, fh)

            code, out, _ = run_cli(["compare", baseline, current])
            self.assertEqual(code, 1)
            self.assertIn("[regression]", out)
            self.assertIn("baseline < | > current", out)


if __name__ == "__main__":
    unittest.main()
