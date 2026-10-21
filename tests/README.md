# Test suites

The tests import the same `agentic_dt` package used by the CLI. Core code stays in
that package; there is no separate test implementation of the runtime.

## Local: safe default

```bash
.venv/bin/python -m pytest -q
# Or select only offline tests:
.venv/bin/python -m pytest tests/local -q
```

`local/` includes unit and offline integration tests: frozen inputs, citations,
human review, append-only recovery, dependencies, evaluation, reports, and the
fictional tutorial. SDK tests use its real HTTP serialization and response
parsing with HTTPX MockTransport, without contacting the provider. Network
connections and DNS lookup are blocked during local test functions, regardless
of whether `OPENAI_API_KEY` exists.

The shared `conftest.py` gates all tests under `live/`, even if a test lacks its
`live` marker. Tests elsewhere marked `live` are gated too. Subprocess regression
tests verify the actual pytest consent and network controls using fictional
credentials and dummy test bodies; they do not call an API.

## Live: explicit opt-in

Configure `OPENAI_API_KEY` in the local environment; do not put keys in this repo
or paste them into a chat. The runtime does not automatically load `.env` files.

```bash
.venv/bin/python -m pytest tests/live \
  --run-live --live-budget-usd 0.05 -q -s
```

Both the flag and a positive finite budget are required. A key alone does not
authorize execution. Live tests are skipped by ordinary `pytest`, including in CI.

There is currently one live smoke test. It:

1. Copies the current typed configuration into an isolated project with the
   fictional library brief, fictional interview, and scripted human-frame fixture.
2. Makes one real analyst generation, preceded by service-side token counting,
   with automatic retries disabled. It uses the real role prompt and schema.
3. Checks response/request IDs, token usage, passage-ID resolution and strict
   local exact-citation validation,
   deliverable coverage, comparison output, and `awaiting_review` status.
4. Evaluates mechanical checks, then resumes the same run and checks unchanged
   checkpoints/logs without an additional call.
5. Verifies that no ledger exists: there is no simulated human approval of live
   model output and no mutation of the project's main ledger.

Artifacts are retained under `outputs/v2/live-tests/smoke-<id>/`; `-s` displays the
exact directory, including on failure. Every invocation creates a fresh run and
can incur another charge. The budget is the runner's conservative estimate for
this run, not a provider-enforced account cap or a cumulative ceiling across
separate test invocations. Verify configured prices before authorizing spending.

This smoke test checks service compatibility, not research quality, critic
quality, or human learning. A live schema rejection, incomplete response, or
incorrect passage is a real failing result; do not weaken validation to make it
pass. Inspect its saved logs and request before authorizing another attempt.
Use offline HTTP simulations for deliberate timeouts, rate limits, and refusals.

## Model migration

New runs default to `gpt-6-luna`, `reasoning_effort: none`, and Standard
short-context estimates of $0.10 input / $0.50 output per million tokens.
These match the [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
checked on 2026-10-20. The input cap is below the long-context pricing threshold.
The model page documents `gpt-6-luna`, not a dated snapshot; do not invent a
snapshot suffix or treat the alias as a guarantee of unchanged future behavior.

Reasoning effort is passed to both token counting and generation, and frozen
with the model and cost settings in each manifest. The optional field is omitted
from requests for legacy manifests that lack it; old model selections and
manifest bytes are not rewritten. Existing checkpoints remain authoritative.
An unfinished historical run may eventually require its own migration when its
saved model becomes unavailable; no automatic fallback changes its context.
