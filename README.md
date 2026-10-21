# Agentic Reframe 2.0

Help design teams develop and revise their own problem understanding through
attributable evidence, independent interpretations, and structured challenge.

Agentic Reframe is a compact teaching runtime for the front end of a design
thinking project. Its learning unit is an inquiry cycle: record your own frame,
compare an independent AI interpretation, collect discriminating evidence, and
justify a revision. It teaches agentic building blocks without making
multi-agent complexity the default.

A human reviews every claim before it enters the append-only ledger. Acceptance
for investigation is not factual validation. Reports distinguish human framing
decisions from accepted, evidence-supported findings and preserve disagreement.

## Why version 2

Version 1 proved the mechanics with four perspective agents and a synthesis
agent on every exercise. Version 2 keeps its strongest controls while making
specialization conditional:

- one analyst applies systems, human, operational, and opportunity lenses;
- an optional critic has a different audit contract and creates no claims;
- one runner handles every exercise and every resume;
- an independent human frame is frozen before framing runs and withheld from AI;
- one human-review path records decisions, reflection, and later corrections;
- one append-only ledger supports deterministic replay;
- exact passage checks are separate from human-assessed research and reasoning
  quality; better human investigation is an evaluation target, not a claim.

The local version 1 source and fictional run archive is preserved under
`.archive/version-1.0/`. That directory is ignored by Git.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/agentic-dt validate
.venv/bin/agentic-dt tutorial --out outputs/v2/tutorial
.venv/bin/python -m pytest
```

Record your own interpretation before looking at AI output. The worksheet starts
blank; complete all fields yourself. Then preview a scoped request without an
API call:

```bash
.venv/bin/agentic-dt frame \
  --author your-name --out human_input/frame-01.yaml
# Complete human_input/frame-01.yaml before the next command.
.venv/bin/agentic-dt run \
  --exercise frame_challenge \
  --human-frame human_input/frame-01.yaml \
  --out outputs/v2/runs/first-frame \
  --critic
```

Add `--live --budget-usd 0.10` to authorize model calls. Evidence is assigned
explicitly with repeated `--evidence PATH` arguments; the runtime never scans
human-input directories.

## Repository layout and tests

```text
agentic_dt/          Core implementation, shared by the CLI and all tests
tests/conftest.py   Live-test consent gate and offline network boundary
tests/local/        Unit, filesystem, recovery, tutorial, and offline SDK tests
tests/live/         Explicitly budgeted real-API smoke test
config/             Typed project configuration
outputs/v2/         Generated artifacts, ignored by Git
.archive/           Local historical backups, ignored by Git
```

Normal `pytest` runs local tests and skips live tests, even if an API key exists.
Local tests block network connections. To deliberately run the live smoke test,
set `OPENAI_API_KEY` in your environment, then use:

```bash
.venv/bin/python -m pytest tests/live \
  --run-live --live-budget-usd 0.05 -q -s
```

This uses fictional inputs, an isolated run directory, and no automatic retries.
It checks one analyst call and a checkpoint-only resume; it never approves claims
or writes the ledger. Each invocation is a new budgeted run and can incur charges.
See [the test guide](tests/README.md) for scope and safeguards.

New runs use `gpt-6-luna` with explicit `reasoning_effort: none`, keeping the
initial migration close to the previous non-reasoning workflow. Model, effort,
and estimated rates are frozen per run. Existing manifests retain their saved
model and request settings. See [the model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
for supported capabilities and current prices; live account access and output
quality still need verification.

`agentic_dt.egg-info/` is generated setuptools packaging metadata, not core code
or project evidence. The stale version 0.1.0 copy was moved to
`.archive/generated-packaging/`. Editable installation can recreate it; it is
already ignored by Git and does not need to be versioned or archived repeatedly.

## Architecture

```text
human frame (not sent to AI)    brief + exercise + selected evidence/prior claims
              |                                  |
              |                    analyst + optional bounded critic
              |                                  |
              +----------> comparison packet <---+
                                    |
                        human judgment + reflection
                                    |
                            append-only ledger
                                    |
                 new evidence -> new run/correction -> revised frame
                                    |
                      evaluation + deterministic reports
```

Model outputs never receive filesystem, shell, web, or graph-write tools.
Python owns source selection, validation, persistence, budgets, retries,
checkpoints, review, and compilation.

See [the workflow](docs/workflow.md) and [the architecture](docs/architecture.md).
The zero-cost tutorial demonstrates two inquiry rounds and an append-only
correction; its human judgments and evidence are explicitly fictional.

## Scope

The repository supports problem framing, audience and stakeholder research,
landscape and constraint analysis, opportunity reframing, and planning for later
ideation and prototyping. It does not present generated solutions as validated.

## License

Code and architecture files are licensed under Apache License 2.0. Original
exercise concepts derived from IDEO.org Design Kit material retain their source
attribution; repository-authored exercise outlines are CC BY 4.0.
