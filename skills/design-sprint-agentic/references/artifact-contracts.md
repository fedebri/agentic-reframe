# Version 2 artifact contracts

## Run manifest

Every run freezes:

- run and exercise identity;
- required deliverables;
- exact brief and explicitly selected evidence snapshots with SHA-256 hashes;
- reviewed prior context;
- independent human framing snapshot (required for new framing runs, withheld
  from both model requests and never used as factual evidence);
- analyst and optional critic prompts;
- model, explicit reasoning effort when assigned, token, retry, timeout, and
  estimated-price settings;
- the one ledger path the human review may later update.

Resumes use the saved manifest. Any changed manifest or checkpointed response
fails before another model call.
Legacy manifests without reasoning effort omit it from requests; updating the
project's model default never rewrites an existing run or changes its request.
New manifests select `citation_format: passage_ids`. Manifests without that
field retain the historical `line_spans` contract; use a fresh run to adopt IDs.

## Model outputs

The analyst returns typed claim drafts with a local ID, claim type, deliverable,
assigned evidence references, source-local passage IDs, reviewed premises,
confidence, public rationale, and open questions. Python indexes every frozen
source into blank-line-separated blocks without changing the original Markdown.
Model inputs contain each block's text once, with its ID, in source order.
Python resolves references to exact quotations and one-based line spans before
canonical response validation, review, or ledger entry. Unknown references fail
closed. The typed model draft is saved separately as `analyst_draft.json` for
inspection, including on reference failure; it is not a validated checkpoint.
Canonical checkpoints and ledger events retain their exact-citation shape, as
do legacy model outputs. Entailment is not automated.

The critic returns issues and a recommendation. It cannot return claims or graph
events. Its bounded next action is review or request evidence; the latter needs
one discriminating question and hands control to the human.

## Human review

A worksheet is bound to exact manifest, analyst, critic, and base-ledger bytes.
Every claim requires accept/reject. Acceptance is distinct from evidence status.
Evidence judgments retain exact passages and public rationale, including a
reaffirmed status. Framing reviews require a researcher reflection: revised or
defended frame, disagreement, reconsidered assumptions, next question, revision
trigger, and evidence considered. Human-authored revisions have explicit human
confidence and preserve required dependencies.

Applying a review is the only proposal-to-ledger path. A saved event-intent batch
precedes appending. Identical retries recover complete-line prefixes and missing
receipts; changed retries fail. Later decisions need a fresh correction review,
optionally with explicitly assigned new evidence. No automatic truncation.

## Ledger

Supported events are evidence addition, claim addition, dependency edge
addition, review decision, evidence-status judgment, run completion, review
commit, independent human snapshot, and researcher reflection. Current state is
derived by replay. Unusable premises block dependent claims. The store is local
and single-writer; incomplete records and invalid references fail closed.

## Reports

Final narrative sections contain only human-accepted claims with `supported` or
`accepted_tension` evidence status. The synthesis index preserves every claim,
review, status, edge, source, independent frame, and reflection, including
excluded material. Narrative findings require usable, supported dependencies;
human framing decisions appear separately and are not factual findings.

## Evaluation

Source-reference validity and passage accuracy are mechanical checks, not
grounding or learning scores. Optional human assessments record the comparison
condition, evidence grounding, assumption critique, contextual explanation,
investigation value, rationale, and later unassisted work. Fictional reflections
demonstrate the mechanism only; no human-development efficacy is established.
