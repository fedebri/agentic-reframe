# Version 2 workflow

## 1. Validate

```bash
.venv/bin/agentic-dt validate
```

This strictly validates all configuration fields and checks the brief, prompts,
and thirteen exercise definitions.

## 2. Record your own interpretation first

```bash
.venv/bin/agentic-dt frame \
  --author your-name \
  --out human_input/frame-01.yaml
```

Complete the YAML before seeing AI output: framing, observations, assumptions,
an alternative frame, and open questions. Say what is unknown; do not invent
observations. A nonempty independent worksheet is required for new
`frame_challenge` runs, including previews. Other exercises can use the same
checkpoint by supplying a worksheet with their exercise ID.

The runtime freezes this snapshot separately from factual evidence and never
sends it to either model. This protects independence of the AI interpretation;
the software cannot verify whether a person actually worked independently.

## 3. Prepare an exercise

```bash
.venv/bin/agentic-dt run \
  --exercise frame_challenge \
  --human-frame human_input/frame-01.yaml \
  --out outputs/v2/runs/frame-01 \
  --critic
```

Preview is the default. It writes a frozen input manifest and analyst request but
makes no model call. Add explicitly selected UTF-8 text evidence with repeated
`--evidence PATH` options. Images and PDFs are not read directly; supply human
captions, observations, or extracted text. The optional
[fieldwork worksheets](process_templates/hitl_templates.md) support manual
collection. Assign reviewed prior context only when needed with
repeated `--context-claim CLAIM_ID` options.
Sources supporting selected prior claims are included for auditability. Rejected,
contested, invalidated, deprecated, and dependency-blocked context is excluded.

The Markdown inputs remain unchanged. For new runs, Python indexes every frozen
source into blank-line-separated passages (`p1`, `p2`, etc. within each source).
The analyst sees all passage texts in order and cites source/passage IDs, not
model-counted lines or copied quotations. Python supplies the exact quotations
and locations for review and provenance. A compact list is one passage; this is
document indexing, not semantic search or a prescribed interpretation.

This adds no model calls. IDs add input overhead, while references replace
generated quotations and line numbers in the output; net token savings depend on
the documents and citations. Typed output is retained as `analyst_draft.json`,
but only validated `analyst_response.json` is a resumable checkpoint. Unknown
passage references stop the run before review or ledger mutation.

For a passage-indexed run, a new critic request includes those same source
passages and the analyst's passage references, without repeating a full quoted
paragraph in every claim. The canonical analyst checkpoint still retains the
exact quotations and locations for human review. Already saved critic requests
keep their original format on retry. If request construction failed before a
critic request was saved, resuming builds the compact request and reuses the
verified analyst checkpoint without another analyst call.

For a paid call:

```bash
OPENAI_API_KEY=... .venv/bin/agentic-dt run \
  --exercise frame_challenge \
  --human-frame human_input/frame-01.yaml \
  --out outputs/v2/runs/frame-01 \
  --critic \
  --live \
  --budget-usd 0.10
```

The budget reserves the configured maximum output and every permitted attempt.
An ambiguous interrupted call requires `--retry-failed`; previous reservations
remain charged. Resume using the same output, exercise, critic, evidence, and
context selections. A saved, verified response is reused without another call,
including when interruption left `status.json` at `running`. A changed human
frame, evidence selection, or required prior claim needs a fresh run.

New runs use the model and explicit reasoning effort in `config/project.yaml`
(`gpt-6-luna`, effort `none` by default). Both are frozen with cost estimates in
the manifest. Changing the current configuration does not upgrade an existing
run or change its saved API request. Old manifests without a reasoning setting
continue to omit it from requests. Use a fresh run to compare models/settings.
Similarly, manifests without `citation_format` keep the old line-based request
and checkpoint contract. Use a fresh run to adopt passage IDs; existing runs,
including failed live tests, are not silently migrated.
For isolated service verification, use the [live test suite](../tests/README.md)
instead of sending the placeholder project brief or reusing tutorial checkpoints.

## 4. Compare and review

```bash
.venv/bin/agentic-dt review \
  --run outputs/v2/runs/frame-01 \
  --out outputs/v2/reviews/frame-01.yaml \
  --reviewer your-name
```

Read `comparison.md` in the run and the Markdown packet next to the review YAML.
They show your independent frame, the analyst's interpretation, exact quoted
passages with paths and line numbers, uncertainty, and critic findings.

Edit every decision from `pending` to `accept` or `reject`. Acceptance and
evidence status are separate: leave an interpretation `proposed` for inquiry.
Changing or reaffirming evidentiary status requires exact passage citations and
a concise public rationale. A matching quote does not establish that the claim
follows from it; that is a human judgment.

When an independent frame exists, complete `reflection`: revised frame,
unresolved disagreement, assumptions reconsidered, next research question,
evidence that would trigger another revision, and evidence IDs considered.
Disagreement need not be resolved in favor of the model; a justified unchanged
frame is also valid. To author a different claim, set `revised_statement` and
`revision_confidence` on an accepted decision. This creates a new human-attributed
hypothesis, retains and rejects the original, and preserves required premises.

```bash
.venv/bin/agentic-dt review \
  --apply outputs/v2/reviews/frame-01.yaml
```

Application verifies manifest, analyst, and critic hashes and the worksheet's
base ledger snapshot. It saves a recovery batch before appending validated
events. Keep the `.batch.json` beside the YAML and receipt. Retrying unchanged
input resumes complete-record prefixes or reconstructs a missing receipt; it
does not append duplicate events. An incomplete final JSON record fails closed
for explicit recovery, never automatic truncation. Use one ledger writer.

## 5. Gather evidence and revise

The optional critic selects `review` or `request_evidence`, with one
discriminating question for the latter. The host records that request and stops
for human investigation; there is no autonomous fieldwork or extra model loop.

Collect and explicitly assign new evidence to a fresh run. Record a new human
frame before its AI interpretation. Then revisit old claims with a new review:

```bash
.venv/bin/agentic-dt review \
  --run outputs/v2/runs/frame-01 \
  --out outputs/v2/reviews/frame-01-correction.yaml \
  --reviewer your-name \
  --evidence human_input/follow-up.md
```

Add citations to the new frozen sources and update decisions or statuses. Apply
the correction with the same `review --apply` command. Never edit an applied
worksheet and expect it to replace history: changed retries are rejected. A
stale worksheet also requires fresh export if another review changed the ledger.

Use `relations` for explicit `contradicts`, `depends_on`, or other typed edges.
Deprecation requires an `invalidates`/`supersedes` edge from an accepted supported
claim. Accepted tension requires a contradiction edge. Old claims remain
inspectable. Unusable premises block dependent context; final reports also block
claims whose required premises remain merely proposed. To remove a substantive
dependency, make a fresh independently grounded proposal instead of silently
dropping it in a wording revision.

## 6. Evaluate artifacts and human reasoning separately

```bash
.venv/bin/agentic-dt eval \
  --run outputs/v2/runs/frame-01 \
  --out outputs/v2/evals/frame-01.json
```

`source_reference_validity` measures assigned source IDs. `passage_accuracy`
measures exact source text and line spans, not semantic support, truth, or
learning. The report also records deliverable/question coverage, duplication,
critic issues, model attempts, reserved cost, the independent-frame checkpoint,
and the latest human reflection. Reserved cost is a conservative local estimate,
not an invoice. Older `citation_validity` is renamed to avoid overstating it.

Optionally provide a separately completed assessment:

```yaml
run_id: COPY_FROM_input_manifest.json
assessor_id: independent-reviewer
condition: independent_comparison
evidence_grounding: 3
assumption_critique: 3
contextual_explanation: 3
investigation_value: 3
rationale: Explain the observed strengths and limitations with examples.
unassisted_follow_up: Record a later explanation produced without AI assistance.
review_minutes: 15
```

```bash
.venv/bin/agentic-dt eval \
  --run outputs/v2/runs/frame-01 \
  --assessment human_input/assessment.yaml \
  --out outputs/v2/evals/frame-01-rated.json
```

Rate each dimension from 1 (unsupported/absent), through 3 (partly justified), to
5 (well justified with concrete evidence and countercases). Research quality
means grounded, appropriately scoped findings and useful questions. Human
reasoning means recognizing assumptions, explaining context, choosing
discriminating evidence, and revising or defending a frame with reasons.

To test whether repeated use helps people investigate better, compare human-only,
AI-first, and independent-comparison work on comparable cases, with comparable
time, evidence, and budgets. Record the work and condition honestly; the CLI
stores assessments but does not run or validate that experiment. Use blinded
raters where practical and a later unassisted task. Do not equate faster output,
human/model agreement, or schema validity with learning. No efficacy has yet
been established. Require such evidence before enabling more agents or tools.

## 7. Compile

```bash
.venv/bin/agentic-dt compile \
  --ledger outputs/v2/ledger/events.jsonl \
  --out outputs/v2/reports/snapshot-01
```

Only accepted claims with affirmative evidence status and usable supported
dependencies enter factual sections. Accepted tensions require both sides to
remain reportable. Human framing decisions have a separately labeled section:
they are interpretations, not validated findings. Proposed, rejected, contested,
deprecated, and blocked material remains in the provenance index and ledger.

## Zero-cost tutorial

```bash
.venv/bin/agentic-dt tutorial --out outputs/v2/tutorial
```

The tutorial runs a complete fictional cycle against an isolated ledger:
independent initial frame, overstrong analyst hypothesis, AI challenge,
simulated human judgment, a new participant account, a second independent frame,
and a justified correction of the original assumption. It makes no API calls.
Read `TUTORIAL.md`, both comparison packets, `correction.yaml`, the synthesis
index, and the reports. Simulated reflections demonstrate the mechanism, not
measured improvement in human reasoning.
