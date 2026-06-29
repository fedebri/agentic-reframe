# 10. Five Whys

## Purpose

Probe beneath a claim, behavior, constraint, or observation to expose deeper
causes, assumptions, and missing evidence. This exercise can run on top of any
previous exercise output.

## Inputs

- Any active claim or accepted tension from the provenance graph
- Supporting evidence cited by that claim
- Related contradictions or open questions

## Tasks

1. Select a claim, observation, or tension to investigate.
2. Ask why it occurs and record the answer as a new claim or assumption.
3. Repeat until the chain reaches a plausible root cause, evidence gap, or
   circular reasoning risk.
4. Mark each step as evidence-backed, inferred, or assumed.
5. Stop when additional whys would become speculative without new evidence.

## Expected Outcome

- Root-cause or assumption chain.
- Evidence gaps.
- Stopping condition.
- Claims that require validation before final synthesis.

## Provenance Requirements

Each why step must be linked to the prior step with `depends_on`, `refines`, or
`contradicts` edges. Speculative steps must not become facts.

## Source Material

- `10_five_whys.html`
