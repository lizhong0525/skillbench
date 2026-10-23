import json
import unittest
from unittest import mock as umock

from skillbench.adapters import (
    MockAdapter,
    OpenAICompatAdapter,
    create_adapter,
)
from skillbench.errors import AdapterError


class TestMockAdapter(unittest.TestCase):
    def test_echo_is_default_and_deterministic(self):
        adapter = MockAdapter({})
        r1 = adapter.complete("hello world")
        r2 = adapter.complete("hello world")
        self.assertEqual(r1.text, "hello world")
        self.assertEqual(r1.text, r2.text)
        self.assertEqual(r1.prompt_tokens, 2)
        self.assertEqual(r1.total_tokens, r1.prompt_tokens + r1.completion_tokens)

    def test_template_mode(self):
        adapter = MockAdapter({"mock": {"mode": "template", "template": "OUT: {prompt}"}})
        self.assertEqual(adapter.complete("in").text, "OUT: in")

    def test_template_mode_missing_template(self):
        adapter = MockAdapter({"mock": {"mode": "template"}})
        with self.assertRaises(AdapterError):
            adapter.complete("in")

    def test_map_mode_with_fallback(self):
        adapter = MockAdapter({"mock": {"mode": "map", "responses": {"q1": "a1"}}})
        self.assertEqual(adapter.complete("q1").text, "a1")
        self.assertEqual(adapter.complete("unknown").text, "unknown")

    def test_unknown_mode(self):
        adapter = MockAdapter({"mock": {"mode": "psychic"}})
        with self.assertRaisesRegex(AdapterError, "Unknown mock mode"):
            adapter.complete("in")


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestOpenAICompatAdapter(unittest.TestCase):
    def test_missing_api_key(self):
        with umock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(AdapterError, "API_KEY"):
                OpenAICompatAdapter({"model": "m"})

    def test_success_parses_text_and_usage(self):
        env = {"SKILLBENCH_API_KEY": "test-key", "SKILLBENCH_MODEL": "test-model"}
        payload = {
            "choices": [{"message": {"content": "the answer"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        with umock.patch.dict("os.environ", env, clear=True):
            adapter = OpenAICompatAdapter({})
            with umock.patch(
                "urllib.request.urlopen", return_value=FakeHTTPResponse(payload)
            ) as mocked:
                resp = adapter.complete("hi")
        self.assertEqual(resp.text, "the answer")
        self.assertEqual(resp.total_tokens, 5)
        request = mocked.call_args[0][0]
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")

    def test_http_error_raises_adapter_error(self):
        import io
        import urllib.error

        env = {"SKILLBENCH_API_KEY": "test-key"}
        err = urllib.error.HTTPError(
            "http://x", 401, "Unauthorized", {}, io.BytesIO(b'{"error": "bad key"}')
        )
        with umock.patch.dict("os.environ", env, clear=True):
            adapter = OpenAICompatAdapter({"model": "m"})
            with umock.patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaisesRegex(AdapterError, "HTTP 401"):
                    adapter.complete("hi")

    def test_malformed_response_shape(self):
        env = {"SKILLBENCH_API_KEY": "test-key"}
        with umock.patch.dict("os.environ", env, clear=True):
            adapter = OpenAICompatAdapter({"model": "m"})
            with umock.patch(
                "urllib.request.urlopen", return_value=FakeHTTPResponse({"oops": True})
            ):
                with self.assertRaisesRegex(AdapterError, "Unexpected API response"):
                    adapter.complete("hi")


class TestRegistry(unittest.TestCase):
    def test_create_mock(self):
        self.assertIsInstance(create_adapter("mock", {}), MockAdapter)

    def test_unknown_adapter(self):
        with self.assertRaisesRegex(AdapterError, "Unknown adapter"):
            create_adapter("telepathy", {})


if __name__ == "__main__":
    unittest.main()
