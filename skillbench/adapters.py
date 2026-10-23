"""Model adapter interface plus the mock and OpenAI-compatible adapters."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .errors import AdapterError


@dataclass
class ModelResponse:
    """One completion returned by an adapter."""

    text: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None


class ModelAdapter:
    """Pluggable adapter interface: one method, ``complete``."""

    name = "base"

    def __init__(self, settings: Optional[Mapping[str, Any]] = None) -> None:
        self.settings = dict(settings or {})

    def complete(
        self, prompt: str, messages: Optional[List[Dict[str, str]]] = None
    ) -> ModelResponse:
        raise NotImplementedError


class MockAdapter(ModelAdapter):
    """Deterministic, offline adapter for tests and demos.

    Modes (suite ``model.mock.mode``):
      - echo:     reply with the rendered prompt verbatim (default).
      - template: reply with the ``model.mock.template`` string where ``{prompt}``
                  is substituted with the rendered prompt.
      - map:      look the rendered prompt up in ``model.mock.responses``; falls
                  back to echo behaviour when the prompt is not mapped.

    Token counts are a deterministic word-count estimate so reports always
    include usage numbers for this adapter.
    """

    name = "mock"

    def complete(
        self, prompt: str, messages: Optional[List[Dict[str, str]]] = None
    ) -> ModelResponse:
        mock_cfg = self.settings.get("mock") or {}
        if not isinstance(mock_cfg, dict):
            raise AdapterError("'model.mock' must be a mapping if present")
        mode = mock_cfg.get("mode", "echo")

        if mode == "echo":
            text = prompt
        elif mode == "template":
            template = mock_cfg.get("template")
            if not isinstance(template, str):
                raise AdapterError("mock mode 'template' requires model.mock.template")
            text = template.replace("{prompt}", prompt)
        elif mode == "map":
            responses = mock_cfg.get("responses") or {}
            if not isinstance(responses, dict):
                raise AdapterError("mock mode 'map' requires model.mock.responses mapping")
            text = responses.get(prompt, prompt)
        else:
            raise AdapterError(
                f"Unknown mock mode '{mode}'; expected echo, template, or map"
            )

        prompt_tokens = len(prompt.split())
        completion_tokens = len(text.split())
        return ModelResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )


class OpenAICompatAdapter(ModelAdapter):
    """OpenAI-compatible /chat/completions endpoint, configured via env vars.

    Environment:
      SKILLBENCH_API_KEY   (or OPENAI_API_KEY)    required bearer token
      SKILLBENCH_BASE_URL  (or OPENAI_BASE_URL)   default https://api.openai.com/v1
      SKILLBENCH_MODEL     (or OPENAI_MODEL)      fallback model name

    The suite's ``model.model`` overrides SKILLBENCH_MODEL. Network or API
    failures raise AdapterError with the HTTP detail.
    """

    name = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(settings)
        self.api_key = os.environ.get("SKILLBENCH_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        self.base_url = (
            os.environ.get("SKILLBENCH_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise AdapterError(
                "OpenAI-compatible adapter requires SKILLBENCH_API_KEY "
                "(or OPENAI_API_KEY) to be set"
            )

    def complete(
        self, prompt: str, messages: Optional[List[Dict[str, str]]] = None
    ) -> ModelResponse:
        model = (
            self.settings.get("model")
            or os.environ.get("SKILLBENCH_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if not model:
            raise AdapterError(
                "No model configured: set model.model in the suite or "
                "SKILLBENCH_MODEL/OPENAI_MODEL in the environment"
            )

        if messages is None:
            messages = [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {"model": model, "messages": messages}
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if key in self.settings:
                payload[key] = self.settings[key]

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AdapterError(
                f"API request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AdapterError(f"Cannot reach {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AdapterError(f"API returned invalid JSON: {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError(
                f"Unexpected API response shape (missing choices[0].message.content): {exc}"
            ) from exc

        usage = data.get("usage") or {}
        return ModelResponse(
            text=text,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw=data,
        )


_REGISTRY = {
    MockAdapter.name: MockAdapter,
    OpenAICompatAdapter.name: OpenAICompatAdapter,
}


def create_adapter(name: str, settings: Optional[Mapping[str, Any]] = None) -> ModelAdapter:
    cls = _REGISTRY.get(name)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY))
        raise AdapterError(f"Unknown adapter '{name}'; available: {known}")
    return cls(settings)
