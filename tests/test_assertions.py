import unittest

from skillbench.assertions import check_assertion
from skillbench.suite import AssertionSpec


def spec(t, value=None):
    return AssertionSpec(type=t, value=value)


class TestAssertions(unittest.TestCase):
    def test_contains_pass_fail(self):
        self.assertTrue(check_assertion(spec("contains", "world"), "hello world").passed)
        r = check_assertion(spec("contains", "mars"), "hello world")
        self.assertFalse(r.passed)
        self.assertIn("mars", r.message)

    def test_not_contains(self):
        self.assertTrue(check_assertion(spec("not_contains", "mars"), "hello").passed)
        self.assertFalse(check_assertion(spec("not_contains", "hell"), "hello").passed)

    def test_equals(self):
        self.assertTrue(check_assertion(spec("equals", "42"), "42").passed)
        self.assertTrue(check_assertion(spec("equals", 42), "42").passed)  # coercion
        self.assertFalse(check_assertion(spec("equals", "43"), "42").passed)

    def test_starts_ends_with(self):
        self.assertTrue(check_assertion(spec("starts_with", "he"), "hello").passed)
        self.assertFalse(check_assertion(spec("starts_with", "lo"), "hello").passed)
        self.assertTrue(check_assertion(spec("ends_with", "lo"), "hello").passed)
        self.assertFalse(check_assertion(spec("ends_with", "he"), "hello").passed)

    def test_regex(self):
        self.assertTrue(check_assertion(spec("regex", r"\d+"), "abc123").passed)
        self.assertFalse(check_assertion(spec("regex", r"^\d+$"), "abc123").passed)

    def test_regex_invalid_pattern_fails(self):
        r = check_assertion(spec("regex", "([unclosed"), "anything")
        self.assertFalse(r.passed)
        self.assertIn("invalid regex", r.message)

    def test_json_valid(self):
        self.assertTrue(check_assertion(spec("json_valid"), '{"a": 1}').passed)
        self.assertFalse(check_assertion(spec("json_valid"), "not json").passed)

    def test_max_latency_ms(self):
        self.assertTrue(
            check_assertion(spec("max_latency_ms", 100), "x", latency_ms=50).passed
        )
        self.assertFalse(
            check_assertion(spec("max_latency_ms", 100), "x", latency_ms=150).passed
        )
        self.assertFalse(check_assertion(spec("max_latency_ms", 100), "x").passed)

    def test_max_completion_tokens(self):
        self.assertTrue(
            check_assertion(
                spec("max_completion_tokens", 10), "x", completion_tokens=5
            ).passed
        )
        self.assertFalse(
            check_assertion(
                spec("max_completion_tokens", 10), "x", completion_tokens=50
            ).passed
        )
        self.assertFalse(
            check_assertion(spec("max_completion_tokens", 10), "x").passed
        )

    def test_unknown_type_fails_closed(self):
        r = check_assertion(spec("vibes", "good"), "hello")
        self.assertFalse(r.passed)
        self.assertIn("unknown assertion type", r.message)


if __name__ == "__main__":
    unittest.main()
