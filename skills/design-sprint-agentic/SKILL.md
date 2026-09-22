---
name: design-sprint-agentic
description: Run or extend this repository's agentic design-sprint tutorial workflow. Use when working with docs/brief.md, exercises/, human-in-the-loop design research evidence, provenance-tagged claims, least-privilege design agents, MCP-shaped adapters, or final discovery artifacts such as framed challenges, audiences, persona maps, constraints, How Might We reframings, and project plans.
---

# Design Sprint Agentic

## Overview

Use this skill to preserve the tutorial workflow's core discipline: exercise
outputs are independent, claims are provenance-tagged, inconsistencies are
explicit, and final design-sprint artifacts are compiled only from active
claims or accepted tensions.

## Workflow

1. Read `AGENTS.md`, `config/project.yaml`, and the relevant agent profile in
   `agents/`.
2. Load the ordered exercise registry from `config/project.yaml`.
3. For each exercise, build a scoped task bundle from the brief, exercise
   definition, available human evidence, and active graph claims.
4. Run the four reasoning-agent perspectives independently.
5. Use the Sovereign Synthesizer to merge, confront, and append graph events.
6. Generate missing human-input templates when configured evidence is absent.
7. Compile final artifacts from active claims, accepted tensions, and cited
   evidence only.

## Required Guardrails

- Enforce least privilege. Do not grant agents broad filesystem access.
- Keep graph updates append-only.
- Log stage, agent, input manifest, output manifest, warning, and validation
  events as structured JSONL.
- Log public reasoning summaries, not hidden chain-of-thought.
- Treat voting as prioritization only. Evidence determines validity.
- Preserve contradictions as productive tensions unless stronger evidence
  invalidates a claim.

## Reference

Read `references/artifact-contracts.md` when implementing schemas, graph events,
logs, or final artifact compilers.
