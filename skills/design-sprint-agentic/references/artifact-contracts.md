# Artifact Contracts

## Takeaway

Required fields:

- `takeaway_id`: stable claim identifier.
- `exercise_id`: configured exercise ID.
- `agent_id`: originating agent.
- `claim`: concise statement.
- `claim_type`: one of `observation`, `inference`, `assumption`, `hypothesis`.
- `evidence_refs`: source IDs or paths.
- `confidence`: float from 0 to 1.
- `validation_status`: one of `proposed`, `supported`, `contested`,
  `deprecated`, `accepted_tension`.
- `public_reasoning_summary`: concise rationale using cited evidence.
- `open_questions`: list of questions that would improve confidence.

## Graph Event

Required fields:

- `event_id`
- `run_id`
- `timestamp`
- `event_type`: `claim_added`, `edge_added`, `status_changed`,
  `evidence_added`, `conflict_classified`
- `subject_id`
- `payload`
- `source_agent_id`
- `exercise_id`

Graph events are append-only. Current state is derived by replaying events.

## Edge Types

- `supports`
- `contradicts`
- `refines`
- `generalizes`
- `depends_on`
- `invalidates`
- `supersedes`

## Log Event

Required fields:

- `run_id`
- `timestamp`
- `stage_id`
- `exercise_id`
- `agent_id`
- `event_type`
- `input_manifest`
- `output_manifest`
- `graph_event_ids`
- `public_reasoning_summary`
- `warnings`
- `validation_status`

Do not log hidden chain-of-thought, credentials, or unassigned private files.

## Final Artifact Rule

Every final artifact statement must cite at least one active graph claim or an
accepted tension. Statements derived from deprecated claims must be blocked
unless a later graph event supplies stronger evidence and explicitly supersedes
the deprecation.

## Provenance implementation decisions

- `agentic_dt/schemas.py` implements evidence, claims, response envelopes, edges,
  status changes, review decisions, and completion-log records. Conflict
  classification events remain for the synthesis package.
- Evidence IDs resolve to retained UTF-8 source snapshots, SHA-256 hashes, and
  one-based inclusive excerpt line ranges. Every claim cites at least one source,
  which may be a brief supporting an explicitly labeled assumption.
- New claims start as `proposed`. Status changes are separate events. Deprecation
  requires an `invalidates` or `supersedes` edge from a supported claim. Deprecated
  claims cannot be revived in place in this version; create a new claim if needed.
- `review_recorded` extends the event types with a reviewer ID, public rationale,
  and `pending`, `accepted`, or `rejected` decision. This is separate from claim
  status and does not authenticate the reviewer.
- Current report eligibility requires `supported` or `accepted_tension` status
  and accepted review. Invalidation targets, and conclusions depending on them
  through `depends_on` or `supports`, are blocked. Tensions require a contradiction
  edge and must retain both sides in any future report.
- Eligibility does not establish truth. Preserve claim type, qualifications, and
  source context. Confidence is not a calibrated probability.
- Each demonstration has a separate run-scoped graph file; IDs are unique within
  that run. The durable identity is `(run_id, subject_id)`. A file rejects events
  from another run. Multi-run graph queries remain out of scope.

## First-pass boundary

- `FirstPassResponse` uses the shared agent/claim envelope with 1–12 takeaways.
  The prompt requests 3–8. Model-facing fields are all required for strict JSON
  schema output; every claim must have status `proposed`.
- The only assigned evidence ID is `brief`. The agent's own profile and exercise 1
  are method instructions, not factual sources. Source snapshots and hashes are
  saved in the run's input manifest, alongside model settings and empty tool/prior
  context assignments.
- Variables, mechanisms, and framing candidates are expressed as claims in this
  first experiment. Dedicated executive-summary and edge output fields from the
  broader agent-profile contract remain for later packages.
- Responses are validated for schema, assigned agent/exercise identity, unique
  claim IDs, and known evidence references. This does not prove citation support
  or evidence quality. Valid outputs await synthesis and review; no graph writes
  or human approval events occur in the first-pass path.
- `LogEvent.details` carries structured API IDs, attempt numbers, token usage,
  cost estimates/reservations, elapsed times, and error types. Missing usage is
  represented as null, never zero. Credentials and full API response objects are
  not persisted in these logs.
