# Agentic Reframe

> **A multi-agent engine for structured inquiry, challenge framing, and epistemic synthesis.**

**Agentic Reframe** is an experimental exploration of agentic software design applied to the earliest stages of problem solving.

In my experience with structured innovation and design processes, two recurring limitations emerge.

- **Limited diversity of reasoning** reduces the breadth of exploration, narrows the space of possible interpretations, and increases the likelihood of converging prematurely on familiar solutions.

- **Insufficient epistemic traceability** makes it difficult to reconstruct the logical path connecting observations, evidence, assumptions, hypotheses, validations, and decisions. As a result, important design choices may become influenced by intuition, cognitive biases, or group dynamics without making those influences explicit.

Agentic Reframe explores whether a collection of specialized reasoning agents can produce richer and more balanced challenge framings than a single reasoning process. In parallel, it builds a provenance-aware knowledge graph that makes the evolution of ideas explicit, allowing conclusions, assumptions, supporting evidence, and contradictions to remain connected and auditable throughout the design process.

Rather than generating solutions, the project focuses on a more fundamental question:

> **How can multiple specialized AI agents help us construct a better representation of a problem before ideation begins?**

The system takes a challenge brief together with optional supporting material and executes a sequence of structured analytical exercises inspired by design thinking, systems thinking, and collaborative reasoning. Independent reasoning agents analyze the problem from complementary perspectives before a synthesis agent consolidates the findings into a coherent, traceable challenge framing.

The long-term objective is not to replace human judgment, but to augment it through structured inquiry, explicit reasoning, and transparent provenance.

---

# Project Status

> **Early development**

---

# Project Scope

## Challenge framing before solution generation

Agentic Reframe deliberately stops before ideation and prototyping.

Its objective is not to generate solutions, but to improve the quality of the problem representation that precedes solution generation.

The system supports the framing phase by combining:

- multiple independent reasoning agents with complementary analytical perspectives;
- structured agent-to-agent synthesis;
- provenance-aware logical tracking;
- human-in-the-loop contributions;
- structured design exercises.

The intended outcome is a richer understanding of the challenge, broader exploration of possible interpretations, and a transparent record of how conclusions emerged before any design solution is proposed.

---

## Independent reasoning

Multiple agents approach the same exercise independently using different analytical lenses.

Diversity of reasoning is treated as a feature rather than a source of inconsistency.

---

## Explicit synthesis

A dedicated synthesis agent merges observations while preserving:

- agreement;
- disagreement;
- uncertainty;
- supporting evidence;
- provenance.

The goal is not forced consensus.

---

## Traceability

Every important conclusion should answer:

- Where did it originate?
- Which agent proposed it?
- Which evidence supports it?
- Has it been validated?
- Has it been challenged later?

The system therefore maintains an append-only provenance graph rather than a mutable collection of notes.

---

## Human-in-the-loop

Human expertise is considered a first-class input.

Interviews, field observations, photographs, documents, and research notes may all enrich the analytical process.

The system should also recognize when information is missing and generate templates or guidance for collecting it.

---

# High-Level Workflow

```text
docs/brief.md
config/project.yaml
human_input/ and docs/user_input/
exercises/
        |
        v
Input manifest and ordered exercise registry
        |
        v
Per-exercise execution bundle
        |
        v
Parallel reasoning agents
  - Systems Strategist   (Analyst)
  - Human Interpreter    (Diplomat)
  - Operational Realist  (Sentinel)
  - Opportunity Scout    (Explorer)
        |
        v
Sovereign Synthesizer
        |
        v
Append-only provenance graph + structured JSONL logs
        |
        v
Final framing artifacts for later ideation and prototyping
```

Each exercise is treated as an independent action first. The synthesizer then
confronts its takeaways with prior exercise takeaways, records logical
connections, classifies inconsistency, and blocks deprecated claims from final
outputs unless stronger later evidence supersedes them.

---

# Expected Outputs

Each execution should progressively construct a structured representation of the problem, including:

- framed challenge;
- stakeholder definition;
- value proposition canvases;
- landscape and constraint analysis;
- opportunity reframings ("How Might We");
- logical connections between observations;
- provenance-tagged knowledge graph;
- project plan supporting future ideation.

---

# Repository Structure

```text
.
|-- AGENTS.md
|-- README.md
|-- agents/
|   |-- analyst.md
|   |-- diplomat.md
|   |-- sentinel.md
|   |-- explorer.md
|   `-- sythesizer.md
|-- config/
|   `-- project.yaml
|-- docs/
|   |-- brief.md
|   |-- development_plan.md
|   |-- process_templates/
|   |   |-- hitl_templates.md
|   |   `-- generated/
|   `-- user_input/
|-- exercises/
|   |-- README.md
|   |-- 1_frame_challenge.md
|   |-- 2_align_impact_goals.md
|   |-- ...
|   `-- 13_value_proposition_canvas.md
|-- human_input/
|   |-- interviews/
|   |   |-- general/
|   |   |-- expert/
|   |   `-- group/
|   |-- photos/
|   |-- resource_flow/
|   `-- secondary_research/
|-- mcp/
|   `-- manifest.yaml
|-- outputs/
|   |-- exercises/
|   |-- final/
|   |-- graph/
|   `-- logs/
`-- skills/
    `-- design-sprint-agentic/
        |-- SKILL.md
        |-- agents/openai.yaml
        `-- references/artifact-contracts.md
```

The repository is intentionally organized around the separation of:

- reasoning: agent profiles in `agents/`;
- orchestration policy: `AGENTS.md`, `config/project.yaml`, and
  `docs/development_plan.md`;
- MCP-shaped access boundaries: `mcp/manifest.yaml`;
- shared workflow knowledge: `skills/design-sprint-agentic/`;
- external context and human evidence: `docs/`, `human_input/`, and
  `exercises/`;
- canonical exercise definitions: Markdown outlines in `exercises/*.md`;
- optional local source material: ignored imported HTML and PDF assets in
  `exercises/`;
- observability and outputs: `outputs/logs/`, `outputs/graph/`,
  `outputs/exercises/`, and `outputs/final/`.

---

# Technical Goals

The project explores several software engineering concepts:

- multi-agent orchestration;
- planning-first development;
- repository-specific AI configuration;
- Model Context Protocol (MCP);
- reusable agent skills;
- structured logging;
- provenance-aware reasoning;
- modular architecture;
- least-privilege agent design.

---

# Current Architecture

The current repository contains the architectural scaffold and project
contracts. The Python runtime described in `docs/development_plan.md` is the
next implementation step.

```text
Repo-specific configuration
  - AGENTS.md
  - config/project.yaml
  - mcp/manifest.yaml
  - skills/design-sprint-agentic/
        |
        v
Planned local runtime
  - config loader
  - exercise loader
  - least-privilege task bundler
  - MCP-shaped local adapters
  - structured logger
  - append-only graph store
        |
        v
Per-exercise agent execution
  - four independent reasoning agents
  - one Sovereign Synthesizer
        |
        v
Tracked artifacts
  - outputs/exercises/
  - outputs/graph/provenance_events.jsonl
  - outputs/logs/run_events.jsonl
  - docs/process_templates/generated/
  - outputs/final/
```

The design intentionally separates first-pass reasoning from synthesis. The
four reasoning agents cannot write the provenance graph or final artifacts. The
Sovereign Synthesizer is the only agent allowed to append graph events for
exercise synthesis, conflict classification, claim deprecation, and logical
connections across exercises.


---

# Roadmap

## Milestone 1: Repository Scaffold

- Add root project instructions, repo configuration, MCP manifest, agent
  profiles, output folders, human input drop zones, and repo-local skill.
- Status: scaffolded.

## Milestone 2: Schemas and Observability

- Implement typed configuration loading and validation.
- Implement structured JSONL logging.
- Implement graph event models for claims, evidence, edges, status changes,
  and conflict classifications.

## Milestone 3: Exercise Loader

- Load exercises from `config/project.yaml` in deterministic numeric order.
- Treat Markdown outlines in `exercises/*.md` as canonical exercise
  definitions.
- Keep HTML and PDF assets as source material referenced by configuration.

## Milestone 4: Agent Runtime

- Load agent profiles from `agents/*.md`.
- Build scoped per-exercise task bundles.
- Run the four reasoning agents independently.
- Enforce least-privilege read/write boundaries.

## Milestone 5: Synthesis and Provenance Graph

- Implement the Sovereign Synthesizer merge flow.
- Append support, contradiction, refinement, dependency, invalidation, and
  supersession edges.
- Enforce deprecated-claim blocking before final artifact generation.

## Milestone 6: Human-in-the-Loop Evidence and Templates

- Detect available interviews, photos, secondary research, and resource-flow
  material.
- Analyze human evidence when present.
- Generate collection templates when evidence is absent.

## Milestone 7: Final Artifact Compiler

- Compile framed challenge, audience definitions, persona mappings, landscape
  constraints, opportunity reframings, project plan, and provenance report.
- Require every final statement to cite active claims or accepted tensions.

## Milestone 8: Tutorial Verification

- Add a sample brief and smoke test.
- Add focused tests for config validation, graph append-only behavior, conflict
  enforcement, HITL templates, and exercise ordering.
- Document how to inspect logs, graph events, intermediate exercise outputs,
  and final artifacts.

---

# License

Code, configuration, agent definitions, and software architecture files are
licensed under the Apache License 2.0.

Original documentation and exercise outline files authored for this repository
are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).

The exercise concepts and original source method materials that informed the
Markdown outlines in `exercises/*.md` are authored by IDEO.org as part of
Design Kit. This repository attributes that original authorship to IDEO.org.
Imported Design Kit HTML and PDF files are intentionally excluded from
publication through `.gitignore` and are not covered by this repository's
licenses.

---

# Contributing

The project is currently experimental.

Suggestions, critiques, and discussions around agentic architectures, design thinking, knowledge representation, and software engineering are welcome.
