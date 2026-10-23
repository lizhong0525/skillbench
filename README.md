# SkillBench

Regression testing for prompts and agent skills: define expected behavior as explicit assertions in a YAML/JSON suite, run it against a model adapter, and diff reports across prompt versions before you ship a change.

For prompt/skill authors who need to know **what broke** when they edit a prompt — not a vague quality score.

## Quickstart

```bash
pip install pyyaml   # only needed for YAML suites; JSON suites are zero-dependency
python -m skillbench run examples/suite_v1.yaml
```

No API key, no network needed: the default `mock` adapter is deterministic and offline. (Or `pip install .[yaml]` to get a `skillbench` command with YAML support.) No PyYAML? Try the zero-dependency JSON suite: `python -m skillbench run examples/suite_fallback.json`.

## Demo walkthrough

The `examples/` directory contains a summarizer skill in two versions. v1 instructs the model to begin with `"Summary:"`; v2 drops that instruction — a classic silent regression.

1. Baseline run (all cases pass):

```bash
$ python -m skillbench run examples/suite_v1.yaml -o reports/baseline.json
Suite: summarizer-suite (adapter: mock)
Cases: 3  passed: 3  failed: 0  errors: 0  pass rate: 100%
Latency ms: min 0.0  mean 0.0  max 0.0  (wall 0.1)
Total tokens (reported/estimated): 141
  PASS  short paragraph [0 ms]
  PASS  unicode input [0 ms]
  PASS  empty-ish input [0 ms]
Report written to reports/baseline.json
```

2. Run the edited prompt — the assertions catch the missing prefix:

```bash
$ python -m skillbench run examples/suite_v2.yaml -o reports/current.json
Suite: summarizer-suite (adapter: mock)
Cases: 3  passed: 0  failed: 3  errors: 0  pass rate: 0%
  FAIL  short paragraph [0 ms]
        x contains: expected output to contain 'Summary:'
  ...
```

(exit code 1 = assertion failures, 2 = suite/adapter errors)

3. Compare versions side by side:

```bash
$ python -m skillbench compare reports/baseline.json reports/current.json
Comparing baseline suite 'summarizer-suite' vs current suite 'summarizer-suite'
Pass rate: 100% -> 0%
Regressions: 3  Improvements: 0  Output changed (still same status): 0

[regression] empty-ish input: pass -> fail
  baseline < | > current
  * Summary: You are a concise summarizer. Summarize the f~ | Condense the following text. Do not use any prefix.
  < Begin your reply with "Summary:".                       |
    Text:                                                   | Text:
    ...                                                     | ...

[regression] short paragraph: pass -> fail
  ...
```

`compare` exits 1 when regressions exist, so it gates CI.

## Suite format

Suites are YAML (preferred, needs `pip install pyyaml`) or JSON (zero-dependency fallback, see `examples/suite_fallback.json`). Prompt templates use `{variable}` placeholders filled from each case's `input` mapping.

```yaml
name: summarizer-suite
version: "1"
prompt: skills/summarize_v1.md     # path relative to this file
model:
  adapter: mock                    # mock | openai
  mock:
    mode: template                 # echo | template | map
    template: "Summary: {prompt}"
cases:
  - name: short paragraph
    input:
      text: "SkillBench runs prompt regression tests locally."
    assertions:
      - type: contains
        value: "Summary:"
      - type: max_completion_tokens
        value: 200
```

## Assertions

`contains`, `not_contains`, `equals`, `starts_with`, `ends_with`, `regex`, `json_valid`, `max_latency_ms`, `max_completion_tokens`. Unknown types **fail closed** with an explanatory message.

SkillBench never claims semantic quality from a single score. Assertions check exactly what you write; for everything else, record case names under the report's `summary.human_review` list and eyeball them.

## Adapters

- **mock** (default): deterministic, offline. Modes: `echo` (return the rendered prompt), `template` (wrap it), `map` (fixed prompt→response table). Token counts are word-count estimates.
- **openai**: any OpenAI-compatible `/chat/completions` endpoint via env vars — `SKILLBENCH_API_KEY` (or `OPENAI_API_KEY`), `SKILLBENCH_BASE_URL` (or `OPENAI_BASE_URL`, default `https://api.openai.com/v1`), `SKILLBENCH_MODEL` (or suite `model.model`). Usage stats are taken from the API response when present.

Override the suite's adapter with `--adapter mock|openai`. Register your own adapter by adding a `ModelAdapter` subclass to `skillbench/adapters.py:_REGISTRY`.

## CLI

```
python -m skillbench run <suite.yaml|json> [--adapter mock|openai] [-o report.json] [--baseline report.json]
python -m skillbench compare <baseline.json> <current.json>
```

Exit codes: 0 = all passed / no regressions, 1 = assertion failures or regressions, 2 = suite, config, or adapter error.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

57 tests cover suite loading (YAML + JSON), every assertion type, both adapters, the runner, report I/O, comparison/diff logic, and CLI exit codes. The test suite runs fully offline with the mock adapter — no paid API required.

## Known limitations

- One user turn per case; no multi-turn conversations or tool-use traces.
- Side-by-side diffs are line-based; very long single-line outputs get clipped.
- `max_latency_ms` is meaningful only against real (network) adapters.
- No parallel execution; cases run sequentially.
- Windows consoles with legacy code pages print non-ASCII characters as `?` (the data in reports is unaffected).

## Roadmap

1. JUnit XML output for CI test-report UIs.
2. Multi-turn message cases and per-case model overrides.
3. A `review` subcommand that walks `human_review` cases interactively and records verdicts into the report.
