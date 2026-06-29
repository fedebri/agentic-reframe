# 10. Five Whys

## Attribution

Adapted for this agentic workflow from the IDEO.org Design Kit method "The Five
Whys."

## Purpose

Probe beneath a claim, behavior, constraint, or observation to expose deeper
causes, assumptions, and missing evidence. This exercise can run on top of any
previous exercise output.

## Inputs

- Any active claim or accepted tension from the provenance graph
- Supporting evidence cited by that claim
- Related contradictions or open questions

## Procedure

1. Begin with a broad interview question or an active claim about a behavior,
   choice, constraint, or observed pattern.
2. Ask why the first answer or claim is true, then repeat the question several
   times to move from surface explanation toward underlying motivation or cause.
3. Avoid asking sideways questions that broaden the topic. Keep each why linked
   to the previous answer so the chain goes deeper.
4. Record each answer or inference in sequence, noting where the explanation
   appears to become more fundamental.
5. Stop when the chain reaches a plausible root cause, an evidence gap,
   circular reasoning, or speculation that should not be pushed further.

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
