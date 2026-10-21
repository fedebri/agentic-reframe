---
name: design-sprint-agentic
description: Run or extend the version 2 human-led inquiry cycle with independent framing, scoped evidence, structured challenge, correction, provenance, and separate research and human-reasoning evaluation.
---

# Design Sprint Agentic

## Workflow

1. Read `AGENTS.md`, `config/project.yaml`, and the selected exercise.
2. Record the researcher's independent interpretation before framing runs.
   Freeze it separately; never send it to either model or use it as field data.
3. Build a frozen task bundle from the brief, explicitly assigned evidence, and
   reviewed prior ledger claims.
4. Run one analyst using systems, human, operational, and opportunity lenses.
5. Run the critic only when requested or when evaluation policy requires it.
   A request for new evidence hands off to a researcher, not autonomous fieldwork.
6. Compare independent interpretations, exact passages, and critic findings.
   Record human disagreement, assumptions reconsidered, the frame to carry
   forward, a discriminating question, and what would change that judgment.
7. Keep model output outside the ledger until explicit human review. Preserve
   simulated review labels in tutorials; never simulate real human approval.
8. Append a recoverable reviewed batch without rewriting history. Use fresh
   correction worksheets for revised decisions; preserve required dependencies.
9. Evaluate passage mechanics separately from research and human reasoning.
   Compile evidence-qualified findings separately from human framing decisions.

## Guardrails

- No model receives filesystem, web, shell, MCP, or graph-write tools.
- Untrusted evidence and prior claims stay in user-data payloads.
- Use strict structured outputs and validate all references locally.
- Preserve exact source snapshots, hashes, model limits, logs, and response
  checkpoints.
- Keep human acceptance separate from evidence status.
- Do not infer semantic support or learning from exact quotes, model agreement,
  speed, or structural scores. Human-development benefits require real,
  repeatable assessment, including later unassisted investigation.
- Do not log hidden chain-of-thought.
- Do not add agents unless tools, policy, ownership, model, output contract, or
  security context materially changes and evals justify the complexity.

Read `references/artifact-contracts.md` before changing schemas, ledger events,
review, or report compilation.
