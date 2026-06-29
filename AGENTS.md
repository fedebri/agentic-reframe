# Agentic Design Tutorial Repository

This repository is an intro/tutorial project for running the front end of a
design thinking sprint with agentic software practices. It turns
`docs/brief.md`, supporting documents, and the ordered resources in
`exercises/` into evidence-tracked framing artifacts for later ideation and
prototyping.

## Repository Contract

- Treat `docs/brief.md` as the primary challenge input.
- Treat Markdown files under `exercises/` as the canonical ordered exercise
  definitions. The numeric prefix controls execution order, but each exercise
  must be analyzed as an independent action before synthesis.
- Treat HTML and PDF files under `exercises/` as optional local source
  material. They are ignored by Git and must not be required by the runtime.
- Treat `human_input/` and `docs/user_input/` as human-in-the-loop evidence
  drop zones. If evidence is absent, generate the appropriate collection
  template instead of inventing field data.
- Treat `outputs/graph/` as append-only provenance storage. Never rewrite or
  delete claims, evidence, or conflict history.
- Keep ideation and prototyping out of scope. The system may prepare inputs for
  those phases but must not propose final solutions as if they were validated.

## Required Operating Principles

- Use least privilege for every agent. An agent receives only the exercise
  input, prior approved outputs, and graph query access needed for its task.
- Preserve evidence provenance. Every takeaway must point to source document,
  exercise, agent, confidence, validation status, and graph claim IDs.
- Record structured logs for stage, agent, input manifest, output manifest,
  graph mutations, warnings, and validation decisions.
- Do not log hidden chain-of-thought. Log concise public rationale,
  assumptions, evidence references, and decision summaries.
- Prefer explicit schemas and small modules over broad, multi-mode functions.
- Handle inconsistency as design material unless stronger evidence invalidates a
  claim. Deprecated claims remain in the graph with invalidation edges.

## Expected Final Artifacts

The final compiler should produce:

- framed challenge with named audience and correct altitude;
- defined audiences and role distinctions;
- stakeholder persona mappings with pains, gains, and jobs to be done;
- landscape and constraint facts;
- opportunity reframings, usually in How Might We form;
- project plan for later ideation and prototyping phases.

## Local Configuration

Use `config/project.yaml` as the repo-specific configuration source. Use the
agent profiles in `agents/*.md`, the MCP manifest in `mcp/manifest.yaml`, and
the repo-local skill in `skills/design-sprint-agentic/`.
