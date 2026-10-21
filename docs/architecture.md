# Version 2 architecture

## Product requirement

Help design teams develop and revise their own problem understanding through
attributable evidence, independent interpretations, and structured challenge.
The tutorial must expose the agentic building blocks while remaining useful in
real design research. Completion is a justified inquiry decision, not just an
AI-generated document or agreement between agents.

Fayard's human-development perspective makes a testable design requirement:
people should become better investigators through repeated use. The runtime
captures the artifacts needed to study that claim; it does not assume the claim
is true. Independent framing, preserved disagreement, human-authored revisions,
and a concrete next investigation are first-class artifacts.

## Design principles

1. **One capable analyst by default.** Multiple analytical lenses live in one
   prompt. A second agent exists only when its contract is materially different.
2. **Specialization is optional and measurable.** The critic audits evidence,
   logic, scope, and duplication; it cannot create or approve claims.
3. **One execution engine.** Every exercise uses the same prepare, call,
   validate, checkpoint, and resume path.
4. **A small public surface.** The CLI exposes validation, execution, review,
   independent framing, evaluation, compilation, and a tutorial.
5. **A claim ledger, not graph theater.** JSONL events are retained because
   provenance and dependency replay are real requirements. The implementation
   remains deliberately single-writer.
6. **No aspirational permissions.** Version 2 has no MCP runtime. The model has
   no tools; Python enforces every capability boundary.
7. **Configuration is executable truth.** The complete YAML file is strictly
   typed and unknown settings fail validation.
8. **Evaluation precedes expansion.** Mechanical passage checks, human-assessed
   research quality, and human reasoning outcomes are separate. Multi-agent or
   tool additions require repeatable evidence that they justify their cost and
   review burden, without substituting for human investigation.

## Preserved controls

- JSON-schema model outputs and local Pydantic validation;
- untrusted source snapshots in user input, never interpolated into privileged
  instructions;
- explicit evidence selection and immutable input manifests;
- human review before ledger mutation;
- append-only events and deterministic replay;
- bounded transient retries and explicit worst-case cost reservations;
- response hashes and resumable checkpoints;
- no model-controlled filesystem or graph mutation.

## Trust boundaries

The analyst and critic see only their role-specific request payload, not the
entire saved manifest. The human frame is frozen before a framing run but is
deliberately withheld from both models. It is not factual evidence. Exercise and role
instructions are trusted repository content. The brief, evidence, prior claims,
and analyst draft are untrusted user-data payloads. Model output is a proposal,
not an action.

Only `review --apply` can append to the ledger. Report compilation is read-only.

## Source reading and citation

Python assigns source-local IDs to blank-line-separated blocks of each frozen
source. The model receives every block in order, with text supplied once, and
chooses references by source ID and passage ID. It remains free to interpret
sections, core items, competing frames, and gaps; the index makes no semantic
judgments. This adds neither an agent nor a model call or new dependency.

The host resolves the selected blocks into exact quotations and line spans for
the existing canonical checkpoints, review, ledger, and reports. Unknown IDs fail
before claim advancement. The model-facing draft is retained separately for
inspection and is never a substitute for a validated checkpoint. Old manifests
retain their line-based request contract. IDs are scoped to the source snapshot,
not permanent anchors across revisions of a document.

## Inquiry and correction

`inquiry.py` is shared presentation plumbing: run completion and review export
both render the same comparison format. It makes no inference or graph writes.
`review.py` binds decisions to exact run checkpoints and a ledger snapshot, saves
a stable event batch, and appends only after validating the whole batch. Saved
batches support complete-line interruption recovery and receipt reconstruction;
partial JSON records fail closed without rewriting history.

Corrections append new review and validation events. Human revisions create new
claims with human authorship and confidence, not overwritten model text or
inherited model confidence. Required dependencies remain explicit; contested or
invalidated premises exclude their dependents from later context and factual
reports. The compiler separates attributable framing decisions from findings.

The critic's only adaptive choice is `review` versus `request_evidence`, with a
single discriminating question. That choice becomes a public logged handoff to
the researcher, not a model-controlled tool or an unbounded agent loop. Passage
retrieval or further agency remains deferred until a repeatable evaluation shows
that it supports inquiry better than explicit source assignment.

## Growth rule

Do not add another agent because a perspective sounds useful. Add one only when
at least one boundary changes: tools, approval policy, model, ownership, output
contract, or security context. Compare it against the single-analyst baseline
with equal budgets and a repeatable dataset.
