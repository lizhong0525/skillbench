import json
import os
import tempfile
import unittest

from skillbench.errors import SuiteLoadError
from skillbench.suite import HAS_YAML, load_suite, render_prompt

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def write_tmp(text, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class TestLoadSuite(unittest.TestCase):
    def test_load_json_suite(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.json"))
        self.assertEqual(suite.name, "greeter-suite")
        self.assertEqual(len(suite.cases), 2)
        self.assertEqual(suite.cases[0].name, "alice")
        self.assertIn("greeter", suite.prompt_template)
        self.assertEqual(suite.model["adapter"], "mock")

    @unittest.skipUnless(HAS_YAML, "PyYAML not installed")
    def test_load_yaml_suite(self):
        suite = load_suite(os.path.join(FIXTURES, "greeter_suite.yaml"))
        self.assertEqual(suite.name, "greeter-suite-yaml")
        self.assertEqual(suite.model["mock"]["mode"], "echo")

    def test_missing_file(self):
        with self.assertRaises(SuiteLoadError):
            load_suite(os.path.join(FIXTURES, "does_not_exist.json"))

    def test_empty_file(self):
        path = write_tmp("", ".json")
        try:
            with self.assertRaisesRegex(SuiteLoadError, "empty"):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_malformed_json(self):
        path = write_tmp("{not json", ".json")
        try:
            with self.assertRaisesRegex(SuiteLoadError, "Malformed JSON"):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_root_not_mapping(self):
        path = write_tmp("[1, 2]", ".json")
        try:
            with self.assertRaisesRegex(SuiteLoadError, "mapping"):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_missing_prompt_key(self):
        path = write_tmp(json.dumps({"cases": [{"name": "x"}]}), ".json")
        try:
            with self.assertRaisesRegex(SuiteLoadError, "prompt"):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_missing_prompt_file(self):
        path = write_tmp(
            json.dumps({"prompt": "nope.md", "cases": [{"name": "x"}]}), ".json"
        )
        try:
            with self.assertRaisesRegex(SuiteLoadError, "not found"):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_no_cases(self):
        path = write_tmp(json.dumps({"prompt": "greeter.md", "cases": []}), ".json")
        try:
            # prompt path is relative to the suite file, which lives in /tmp here
            with self.assertRaises(SuiteLoadError):
                load_suite(path)
        finally:
            os.unlink(path)

    def test_duplicate_case_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = os.path.join(tmp, "p.md")
            with open(prompt, "w", encoding="utf-8") as fh:
                fh.write("hi {name}")
            suite_path = os.path.join(tmp, "s.json")
            with open(suite_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "prompt": "p.md",
                        "cases": [
                            {"name": "dup", "input": {"name": "a"}},
                            {"name": "dup", "input": {"name": "b"}},
                        ],
                    },
                    fh,
                )
            with self.assertRaisesRegex(SuiteLoadError, "Duplicate"):
                load_suite(suite_path)

    def test_unsupported_extension(self):
        path = write_tmp("prompt: x", ".toml")
        try:
            with self.assertRaisesRegex(SuiteLoadError, "Unsupported"):
                load_suite(path)
        finally:
            os.unlink(path)


class TestRenderPrompt(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(render_prompt("Hi {name}!", {"name": "Ada"}), "Hi Ada!")

    def test_missing_variable(self):
        with self.assertRaisesRegex(SuiteLoadError, "missing input variable"):
            render_prompt("Hi {name}!", {})

    def test_bad_placeholder(self):
        with self.assertRaises(SuiteLoadError):
            render_prompt("Hi {}", {"name": "Ada"})


if __name__ == "__main__":
    unittest.main()
