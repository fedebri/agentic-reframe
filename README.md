# Agentic Reframe 2.0

A human-led agentic system for design research. It turns a brief, selected
evidence, and structured exercises into reviewed claims and traceable framing
reports for later ideation and prototyping.

## Core system design

- **Bounded agents.** One analyst interprets each exercise. An optional critic
  audits evidence, reasoning, and scope without creating or approving claims.
  Models have no filesystem, shell, web, or ledger-write tools.
- **Host-controlled execution.** Python handles source selection, typed output
  validation, budgets, bounded retries, checkpoints, and resume. Configuration
  lives in [config/project.yaml](config/project.yaml).
- **Explicit context.** Runs freeze the brief, exercise, assigned evidence, and
  selected reviewed claims. Models cite passage IDs; Python resolves exact
  quotations and locations. Evidence directories are never scanned.
- **Human judgment before persistence.** An independent human frame is frozen
  before framing runs and withheld from AI. Review records comparison, decisions,
  disagreement, and the next investigation. Acceptance is separate from factual support.
- **Append-only memory.** Human review is the only path into the claim ledger.
  Corrections preserve history; invalid premises block dependent claims.
  Replay and report compilation are deterministic.
- **Separate evaluation layers.** Citation checks, coverage, and cost are
  measured separately from human-assessed grounding and reasoning quality.
  Structured logs record public rationale and decisions, not hidden reasoning.

```text
brief + exercise + selected evidence/context → analyst → optional critic
                                                        ↓
independent human frame ─────────────────────→ comparison + human review
                                                        ↓
                                             append-only claim ledger
                                                        ↓
                                             reports + next inquiry
```

## Current functionality

- **13 ordered exercises** covering framing, audiences and stakeholders,
  field and secondary research, constraints, opportunities, and project planning.
- **CLI workflow:** `validate`, `frame`, `run`, `review`, `eval`, `compile`, and
  a zero-cost fictional `tutorial`. Runs support request previews, optional live
  calls, checkpoint reuse, and later evidence-based corrections.
- **Research outputs:** comparison packets, review worksheets, evaluation JSON,
  a design research brief, provenance report, and synthesis index. Factual report
  sections require human-accepted, evidence-supported claims and dependencies;
  human framing decisions are labeled separately.

## Status

| Component | Current state |
| --- | --- |
| Core Python runtime | Implemented, with offline unit and integration coverage. |
| [Research website](extensions/web/README.md) | Flask prototype: private projects, drafts, exercise navigation, evidence uploads, review, and report downloads. |
| [Cloudflare adapter](extensions/cloudflare/README.md) | Locally tested Workers/Durable Objects/R2 pilot. Production sign-in and paid model calls remain unverified. |

The Cloudflare pilot runs one analysis at a time with a 12 MiB working-data cap
across the cohort. Backup/restore and representative load checks remain open;
see [deployment status](extensions/cloudflare/DEVELOPMENT_STATUS.md).
Research quality and learning benefits have not been established by the fictional
tutorial or structural checks.

Currently accessible to selected testers at: https://agentic-reframe.drvr-web.workers.dev/
