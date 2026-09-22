"""Typed provenance records for the local, single-writer tutorial graph."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    create_model,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Status = Literal["proposed", "supported", "contested", "deprecated", "accepted_tension"]
Review = Literal["pending", "accepted", "rejected"]


class Record(BaseModel):
    """Reject unknown fields at the provenance input boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(Record):
    """Preserve source content and a one-based inclusive excerpt location."""

    source_id: Text
    source_path: Text
    snapshot: str
    content_sha256: Text
    start_line: int = Field(strict=True, ge=1)
    end_line: int = Field(strict=True, ge=1)

    @model_validator(mode="after")
    def valid_snapshot(self) -> Self:
        digest = hashlib.sha256(self.snapshot.encode("utf-8")).hexdigest()
        if digest != self.content_sha256:
            raise ValueError(f"Source {self.source_id}: snapshot hash mismatch")
        if not self.start_line <= self.end_line <= len(self.snapshot.splitlines()):
            raise ValueError(f"Source {self.source_id}: invalid excerpt line range")
        return self


class Claim(Record):
    """A takeaway with provenance; evidence status is separate from human review."""

    takeaway_id: Text
    exercise_id: Text
    agent_id: Text
    claim: Text
    claim_type: Literal["observation", "inference", "assumption", "hypothesis"]
    evidence_refs: list[Text] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    validation_status: Status = "proposed"
    public_reasoning_summary: Text
    open_questions: list[str] = Field(default_factory=list)


class AgentResponse(Record):
    """Shared claim envelope for future role-specific model responses."""

    agent_id: Text
    exercise_id: Text
    takeaways: list[Claim]

    @model_validator(mode="after")
    def matching_origins(self) -> Self:
        for claim in self.takeaways:
            if (claim.agent_id, claim.exercise_id) != (self.agent_id, self.exercise_id):
                raise ValueError(f"Claim {claim.takeaway_id}: response origin mismatch")
        ids = [claim.takeaway_id for claim in self.takeaways]
        if len(ids) != len(set(ids)):
            raise ValueError("Response contains duplicate takeaway IDs")
        return self


class ProposedClaim(Claim):
    """Model-facing first-pass claim; all JSON schema properties are required."""

    agent_id: Literal["systems_strategist"]
    exercise_id: Literal["frame_challenge"]
    validation_status: Literal["proposed"]
    open_questions: list[str]


class FirstPassResponse(AgentResponse):
    """Bounded first-pass response, before synthesis or human approval."""

    agent_id: Literal["systems_strategist"]
    exercise_id: Literal["frame_challenge"]
    takeaways: list[ProposedClaim] = Field(min_length=1, max_length=12)


class FramingClaim(Claim):
    """Proposed exercise-1 claim from any configured reasoning perspective."""

    exercise_id: Literal["frame_challenge"]
    validation_status: Literal["proposed"]
    open_questions: list[str]


class FramingResponse(AgentResponse):
    """Shared bounded envelope; the request restricts agent IDs to the assignee."""

    exercise_id: Literal["frame_challenge"]
    takeaways: list[FramingClaim] = Field(min_length=1, max_length=12)


def framing_response_model(agent_id: str) -> type[FramingResponse]:
    """Constrain both the wire schema and local validation to one assignee."""
    claim = create_model(
        "AssignedFramingClaim",
        __base__=FramingClaim,
        agent_id=(Literal[agent_id], ...),
    )
    return create_model(
        "AssignedFramingResponse",
        __base__=FramingResponse,
        agent_id=(Literal[agent_id], ...),
        takeaways=(list[claim], Field(min_length=1, max_length=12)),
    )


class FirstPassReview(Record):
    """Explicit human retention decision bound to exact saved response bytes."""

    run_id: Text
    response_sha256: Text
    reviewer_id: Text
    retained_claim_ids: list[Text] = Field(min_length=1)
    public_reasoning_summary: Text
    qualification: Text


class SynthesisClaim(FramingClaim):
    """New proposed conclusion with references to its reasoning-agent premises."""

    agent_id: Literal["sovereign_synthesizer"]
    derived_from: list[Text] = Field(min_length=1)


class FramingConflict(Record):
    """An unresolved disagreement; both original claims must be retained."""

    source_id: Text
    target_id: Text
    classification: Literal["productive_tension", "evidence_gap", "scope_conflict"]
    public_reasoning_summary: Text


class FramingSynthesis(AgentResponse):
    """Provisional framing and explicit conflicts, without evidence promotion."""

    agent_id: Literal["sovereign_synthesizer"]
    exercise_id: Literal["frame_challenge"]
    takeaways: list[SynthesisClaim] = Field(min_length=1, max_length=8)
    framed_challenge_id: Text
    conflicts: list[FramingConflict]


class Edge(Record):
    """Relation between claims; invalidates points to the old claim."""

    source_id: Text
    target_id: Text
    relation: Literal[
        "supports",
        "contradicts",
        "refines",
        "generalizes",
        "depends_on",
        "invalidates",
        "supersedes",
    ]
    public_reasoning_summary: Text


class StatusChange(Record):
    """Evidence-based status decision, not a confidence vote."""

    status: Status
    evidence_refs: list[Text] = Field(min_length=1)
    public_reasoning_summary: Text


class ReviewDecision(Record):
    """Recorded human decision; authentication and workflow pausing come later."""

    decision: Review
    reviewer_id: Text
    public_reasoning_summary: Text


class EventBase(Record):
    """Common event metadata; file order is the replay order."""

    event_id: Text
    run_id: Text
    timestamp: datetime
    subject_id: Text
    source_agent_id: Text
    exercise_id: Text


class EvidenceAdded(EventBase):
    """Register a source snapshot."""

    event_type: Literal["evidence_added"] = "evidence_added"
    payload: Evidence


class ClaimAdded(EventBase):
    """Introduce a proposed claim."""

    event_type: Literal["claim_added"] = "claim_added"
    payload: Claim


class EdgeAdded(EventBase):
    """Introduce a logical connection."""

    event_type: Literal["edge_added"] = "edge_added"
    payload: Edge


class StatusChanged(EventBase):
    """Change current status while retaining the original claim."""

    event_type: Literal["status_changed"] = "status_changed"
    payload: StatusChange


class ReviewRecorded(EventBase):
    """Append a review decision independently of evidence status."""

    event_type: Literal["review_recorded"] = "review_recorded"
    payload: ReviewDecision


GraphEvent = Annotated[
    EvidenceAdded | ClaimAdded | EdgeAdded | StatusChanged | ReviewRecorded,
    Field(discriminator="event_type"),
]


class LogEvent(Record):
    """Public execution record; no private reasoning or credentials."""

    run_id: Text
    timestamp: datetime
    stage_id: Text
    exercise_id: Text
    agent_id: Text
    event_type: Text
    input_manifest: list[str]
    output_manifest: list[str]
    graph_event_ids: list[str]
    public_reasoning_summary: Text
    warnings: list[str]
    validation_status: Text
    details: dict[str, JsonValue] = Field(default_factory=dict)
