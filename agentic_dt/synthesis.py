"""Validate synthesis proposals and render an explicitly provisional report."""

from datetime import datetime, timezone

from .graph import EVENT_ADAPTER, GraphState
from .schemas import (
    AgentResponse,
    Evidence,
    FirstPassReview,
    FramingSynthesis,
    GraphEvent,
)


def build_framing_artifacts(
    run_id: str,
    brief: Evidence,
    responses: dict[str, AgentResponse],
    synthesis: FramingSynthesis,
    review: FirstPassReview,
) -> tuple[list[GraphEvent], str]:
    """Keep every original claim; convert permitted proposals to validated events.

    All claims remain proposed. Human retention applies only to explicitly named
    imported claims. This report is a review worksheet, not a final compiler
    result or a bypass of GraphState.reportable_claims().
    """
    originals = {
        f"{agent_id}:{claim.takeaway_id}": claim
        for agent_id, response in responses.items()
        for claim in response.takeaways
    }
    synthesized = {claim.takeaway_id: claim for claim in synthesis.takeaways}
    if synthesis.framed_challenge_id not in synthesized:
        raise ValueError("Selected framing must reference a synthesis claim")
    for claim in synthesis.takeaways:
        unknown = set(claim.derived_from) - originals.keys()
        if unknown:
            raise ValueError(f"Claim {claim.takeaway_id}: unknown premises {unknown}")
    for conflict in synthesis.conflicts:
        if {conflict.source_id, conflict.target_id} - originals.keys():
            raise ValueError("Conflict must reference assigned original claims")

    events = []

    def add(event_type: str, subject: str, payload: dict) -> None:
        events.append(
            EVENT_ADAPTER.validate_python(
                {
                    "event_id": f"{run_id}:event_{len(events) + 1}",
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc),
                    "subject_id": subject,
                    "source_agent_id": "sovereign_synthesizer",
                    "exercise_id": "frame_challenge",
                    "event_type": event_type,
                    "payload": payload,
                }
            )
        )

    add("evidence_added", "brief", brief.model_dump())
    for claim_id, claim in originals.items():
        add("claim_added", claim_id, {**claim.model_dump(), "takeaway_id": claim_id})
    for claim in synthesis.takeaways:
        claim_id = f"sovereign_synthesizer:{claim.takeaway_id}"
        add(
            "claim_added",
            claim_id,
            {**claim.model_dump(exclude={"derived_from"}), "takeaway_id": claim_id},
        )
        for premise in dict.fromkeys(claim.derived_from):
            add(
                "edge_added",
                f"edge_{len(events) + 1}",
                {
                    "source_id": claim_id,
                    "target_id": premise,
                    "relation": "depends_on",
                    "public_reasoning_summary": claim.public_reasoning_summary,
                },
            )
    for conflict in synthesis.conflicts:
        add(
            "edge_added",
            f"edge_{len(events) + 1}",
            {
                "source_id": conflict.source_id,
                "target_id": conflict.target_id,
                "relation": "contradicts",
                "public_reasoning_summary": (
                    f"{conflict.classification}: {conflict.public_reasoning_summary}"
                ),
            },
        )
    for claim_id in review.retained_claim_ids:
        add(
            "review_recorded",
            f"systems_strategist:{claim_id}",
            {
                "decision": "accepted",
                "reviewer_id": review.reviewer_id,
                "public_reasoning_summary": (
                    "Retained for inquiry; not empirically verified. "
                    f"{review.public_reasoning_summary} {review.qualification}"
                ),
            },
        )

    state = GraphState()
    for event in events:
        state.apply(event)
    selected_id = f"sovereign_synthesizer:{synthesis.framed_challenge_id}"
    lines = [
        "# Provisional challenge framing — human review worksheet",
        "",
        "All claims remain proposed. No new evidence or final approval is implied.",
        "Source qualifications (including fictional context) remain in force.",
        f"Run: `{run_id}`. Graph identities are `(run_id, claim_id)`.",
        "",
        "## Proposed working frame",
        "",
        state.claims[selected_id].claim,
        "",
        f"Graph claim: `{selected_id}` (details and premises below).",
        "",
        "## Prior human review",
        "",
        review.public_reasoning_summary,
        "",
        review.qualification,
        "",
        f"Bound to prior run `{review.run_id}`, response SHA-256 "
        f"`{review.response_sha256}`. New outputs still await human review.",
        "",
        "## Unresolved disagreements",
        "",
    ]
    if not synthesis.conflicts:
        lines.append("The synthesizer reported none; this is not proof of consensus.")
    for conflict in synthesis.conflicts:
        lines.append(
            f"- `{conflict.source_id}` / `{conflict.target_id}` "
            f"({conflict.classification}): {conflict.public_reasoning_summary}"
        )
    lines.extend(["", "## All retained claims", ""])
    for claim_id, claim in state.claims.items():
        lines.extend(
            [
                f"### {claim_id}",
                "",
                claim.claim,
                "",
                f"Agent: {claim.agent_id}; exercise: {claim.exercise_id}; "
                f"type: {claim.claim_type}; confidence: {claim.confidence} "
                "(model self-assessment).",
                f"Validation: proposed; human review: {state.reviews[claim_id]} "
                "(acceptance means retained for inquiry).",
                f"Evidence: `brief`, {brief.source_path}:{brief.start_line}; "
                f"SHA-256 `{brief.content_sha256}`. Snapshot retained in graph.",
                "",
                f"Public rationale: {claim.public_reasoning_summary}",
                "",
            ]
        )
        premises = [
            edge.target_id
            for edge in state.edges.values()
            if edge.source_id == claim_id and edge.relation == "depends_on"
        ]
        if premises:
            lines.append("Premises: " + ", ".join(f"`{p}`" for p in premises))
        lines.extend(
            f"- Open question: {question}" for question in claim.open_questions
        )
        lines.append("")
    lines.extend(
        [
            "## Next human checkpoint",
            "",
            "Review the working frame, disagreements, and unsupported assumptions. "
            "Keep, qualify, or challenge proposals before proceeding to impact goals. "
            "No exercise-2 execution or automatic acceptance occurs here.",
            "",
        ]
    )
    return events, "\n".join(lines)
