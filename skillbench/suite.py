"""Test-suite loading and validation.

A suite is a YAML file (preferred, when PyYAML is importable) or a JSON file
(fallback). Schema:

    name: my-suite                # optional, defaults to file stem
    version: "1"                  # optional free-form version tag
    prompt: skills/summarize.md   # path to a prompt/skill template, relative to the suite file
    model:                        # optional model/provider settings
      adapter: mock               # mock | openai
      model: gpt-4o-mini          # model name (openai adapter; mock ignores it)
      temperature: 0.0            # optional sampling params passed through
      max_tokens: 512
      mock:                       # optional mock-adapter behaviour
        mode: template            # echo | template | map
        responses: {}             # mode=map: rendered-prompt -> response
    cases:
      - name: short text
        input:
          text: "..."
        assertions:
          - type: contains
            value: "summary"

Prompt templates use ``str.format`` substitution with the case's ``input``
mapping (``{text}`` above). Missing keys raise a validation error at run time.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import SuiteLoadError

try:
    import yaml  # type: ignore

    HAS_YAML = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_YAML = False


@dataclass
class AssertionSpec:
    type: str
    value: Any = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Case:
    name: str
    input: Dict[str, Any]
    assertions: List[AssertionSpec]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Suite:
    name: str
    prompt_path: str
    prompt_template: str
    cases: List[Case]
    model: Dict[str, Any]
    version: Optional[str]
    source_path: str


def _load_raw(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise SuiteLoadError(f"Suite file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise SuiteLoadError(f"Cannot read suite file {path}: {exc}") from exc

    if not text.strip():
        raise SuiteLoadError(f"Suite file is empty: {path}")

    ext = os.path.splitext(path)[1].lower()
    data: Any
    if ext in (".yaml", ".yml"):
        if not HAS_YAML:
            raise SuiteLoadError(
                f"{path} is YAML but PyYAML is not installed. "
                "Install it with 'pip install pyyaml' or use a JSON suite instead."
            )
        try:
            data = yaml.safe_load(text)
        except Exception as exc:
            raise SuiteLoadError(f"Malformed YAML in {path}: {exc}") from exc
    elif ext == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SuiteLoadError(f"Malformed JSON in {path}: {exc}") from exc
    else:
        raise SuiteLoadError(
            f"Unsupported suite format '{ext or '(none)'}' for {path}; "
            "use .yaml/.yml or .json"
        )

    if not isinstance(data, dict):
        raise SuiteLoadError(
            f"Suite root must be a mapping/object in {path}, got {type(data).__name__}"
        )
    return data


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SuiteLoadError(msg)


def load_suite(path: str) -> Suite:
    """Load and validate a suite file, resolving the prompt template."""
    data = _load_raw(path)
    source = os.path.abspath(path)
    base_dir = os.path.dirname(source)

    prompt_rel = data.get("prompt") or data.get("skill")
    _require(
        isinstance(prompt_rel, str) and prompt_rel.strip(),
        f"Suite {path} must define a non-empty 'prompt' (or 'skill') path",
    )
    prompt_path = (
        prompt_rel if os.path.isabs(prompt_rel) else os.path.join(base_dir, prompt_rel)
    )
    prompt_path = os.path.normpath(prompt_path)
    if not os.path.isfile(prompt_path):
        raise SuiteLoadError(f"Prompt/skill file not found: {prompt_path} (from {path})")
    try:
        with open(prompt_path, "r", encoding="utf-8") as fh:
            prompt_template = fh.read()
    except OSError as exc:
        raise SuiteLoadError(f"Cannot read prompt file {prompt_path}: {exc}") from exc

    raw_cases = data.get("cases")
    _require(
        isinstance(raw_cases, list) and len(raw_cases) > 0,
        f"Suite {path} must define a non-empty 'cases' list",
    )

    cases: List[Case] = []
    seen_names = set()
    for i, rc in enumerate(raw_cases):
        _require(isinstance(rc, dict), f"Case #{i + 1} in {path} must be a mapping")
        name = rc.get("name")
        _require(
            isinstance(name, str) and name.strip(),
            f"Case #{i + 1} in {path} must have a non-empty 'name'",
        )
        _require(
            name not in seen_names,
            f"Duplicate case name '{name}' in {path}",
        )
        seen_names.add(name)
        inp = rc.get("input", {})
        _require(
            isinstance(inp, dict),
            f"Case '{name}' in {path}: 'input' must be a mapping",
        )
        raw_assertions = rc.get("assertions", [])
        _require(
            isinstance(raw_assertions, list),
            f"Case '{name}' in {path}: 'assertions' must be a list",
        )
        assertions = []
        for j, ra in enumerate(raw_assertions):
            _require(
                isinstance(ra, dict) and isinstance(ra.get("type"), str),
                f"Case '{name}' assertion #{j + 1} in {path} must be a mapping with a 'type'",
            )
            assertions.append(
                AssertionSpec(type=ra["type"], value=ra.get("value"), raw=dict(ra))
            )
        cases.append(Case(name=name, input=inp, assertions=assertions, raw=dict(rc)))

    model = data.get("model", {})
    _require(
        isinstance(model, dict),
        f"Suite {path}: 'model' must be a mapping if present",
    )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = os.path.splitext(os.path.basename(path))[0]

    version = data.get("version")
    if version is not None:
        version = str(version)

    return Suite(
        name=name,
        prompt_path=prompt_path,
        prompt_template=prompt_template,
        cases=cases,
        model=dict(model),
        version=version,
        source_path=source,
    )


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    """Render a prompt template with case inputs using str.format syntax."""
    try:
        return template.format(**variables)
    except KeyError as exc:
        raise SuiteLoadError(
            f"Prompt template references missing input variable {exc}; "
            "check the case's 'input' mapping"
        ) from exc
    except (IndexError, ValueError) as exc:
        raise SuiteLoadError(f"Invalid prompt template placeholder: {exc}") from exc
