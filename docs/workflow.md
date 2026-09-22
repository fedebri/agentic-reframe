# Running the framing workflow

Run commands from the repository root after following the installation steps in
the [README](../README.md). Configuration lives in `config/project.yaml`.
The supplied `docs/examples/library_brief.md` is fictional; the default
`docs/brief.md` is a placeholder to replace with your challenge.

## Validate and preview

```bash
.venv/bin/agentic-dt validate --brief docs/examples/library_brief.md
.venv/bin/agentic-dt provenance-demo
.venv/bin/agentic-dt first-pass --brief docs/examples/library_brief.md
```

Validation checks file structure and the ordered exercise registry, not the
quality of the evidence. The provenance demonstration appends a fictional claim
history. First-pass preview saves a request and source manifest without making
API calls. Inspect the printed run directory: only the brief, exercise 1, and
Systems Strategist profile are assigned. Only the brief is factual evidence.

## Run the first perspective

Set `OPENAI_API_KEY` in your shell environment. The runtime does not automatically
load `.env` files. In zsh, you can enter the key without displaying it:

```zsh
read -rs 'OPENAI_API_KEY?OpenAI API key: '
export OPENAI_API_KEY
```

Choose an explicit per-run budget. For example:

```bash
.venv/bin/agentic-dt first-pass \
  --brief docs/examples/library_brief.md --live --budget-usd 0.10
```

Live mode sends assigned sources to OpenAI for token counting and generation.
The configured model, token limits, timeout, retries, and estimated token prices
are under `first_pass_model`. Before generation, the runtime reserves estimated
cost for permitted attempts. This is an application estimate using configured
rates, not a provider billing cap. Repeating a live command incurs new calls.

A completed run contains `response.json` and readable `response.md`, alongside
its request, source snapshots, and status. Inspect whether each proposed claim
is supported by its cited source; a valid citation ID does not establish truth.

## Record a human review

Continuation currently requires explicitly retaining every first-pass claim for
further inquiry. Retention does not validate those claims as facts. If a claim
needs rejection or revision, stop for review; that workflow is not implemented.

Create a local JSON file, such as `docs/user_input/review.json`, with these
fields. Replace every placeholder using the completed run and your own decision:

```json
{
  "run_id": "<run ID from status.json>",
  "response_sha256": "<SHA-256 of the exact response.json file bytes>",
  "reviewer_id": "<your reviewer identity>",
  "retained_claim_ids": ["<each takeaway_id from response.json, exactly once>"],
  "public_reasoning_summary": "<why you retain these claims for inquiry>",
  "qualification": "<limitations and qualifications for synthesis>"
}
```

On macOS, `shasum -a 256 PATH/response.json` prints the required digest.
The review binds to the original run and exact response bytes. It is a recorded
human decision, not authenticated identity or new evidence about the audience.

## Continue through synthesis

Substitute your completed first-pass directory and review path:

```bash
.venv/bin/agentic-dt frame \
  --from-first-pass outputs/exercises/frame_challenge/<first-pass-run> \
  --review docs/user_input/review.json
```

The angle-bracket run name is a placeholder; replace it before running the
command. Preview prepares requests without API calls or graph mutations.
To execute, append `--live --budget-usd 0.10`, choosing your own total budget for
the four new generation calls and any retries.

The original response is reused. Human Interpreter, Operational Realist, and
Opportunity Scout receive the same saved brief and exercise snapshots, each
with its own profile and no sibling responses. Calls run sequentially. The
Sovereign Synthesizer receives all four validated responses and the saved review.
Python validates references before appending graph events and rendering
`provisional_report.md`. All claims remain proposed; new claims await review.

## Inspect local artifacts

- `outputs/exercises/frame_challenge/<run>/`: requests, snapshots, responses,
  status, and the provisional report when synthesis succeeds.
- `outputs/graph/<run>/`: append-only provenance events.
- `outputs/logs/<run>/`: structured events, validation decisions, and usage.

These paths, human evidence drop zones, and generated collection forms are
ignored by Git. Keep graph history intact. Each invocation creates a fresh run;
automatic recovery of partially completed runs is not implemented. A failed
required agent prevents synthesis. Inspect status and logs after failures,
including storage failures that may occur after graph events have been appended.

The current workflow executes exercise 1 only. The remaining exercise definitions
describe the intended longer process. Final artifact compilation and general
evidence ingestion are not implemented yet.

## Verify a checkout

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Tests use deterministic fixtures and local files, without paid model calls or
saved development runs.
