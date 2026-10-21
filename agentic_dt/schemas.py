"""Strict data contracts for version 2 runs and the provenance ledger."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ClaimType = Literal["observation", "inference", "assumption", "hypothesis"]
Status = Literal["proposed", "supported", "contested", "deprecated", "accepted_tension"]


class Record(BaseModel):
    """Reject unknown fields so saved artifacts remain dependable interfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenSource(Record):
    """An immutable source snapshot assigned to a model call."""

    source_id: Text
    source_path: Text
    content: str
    content_sha256: Text

    @model_validator(mode="after")
    def valid_hash(self) -> Self:
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if digest != self.content_sha256:
            raise ValueError(f"Source {self.source_id}: content hash mismatch")
        return self


class ContextClaim(Record):
    """A reviewed ledger claim exposed to a later exercise."""

    claim_id: Text
    exercise_id: Text
    statement: Text
    claim_type: ClaimType
    evidence_refs: list[Text] = Field(min_length=1)
    status: Status


class EvidenceCitation(Record):
    """An exact, one-based inclusive passage in an assigned source."""

    source_id: Text
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: Text


class HumanFrame(Record):
    """An independent interpretation recorded before model work begins."""

    author_id: Text
    exercise_id: Text
    framing: Text
    observations: list[Text] = Field(min_length=1)
    assumptions: list[Text] = Field(min_length=1)
    alternative_frame: Text
    open_questions: list[Text] = Field(min_length=1)


class ResearchReflection(Record):
    """Public human judgment following comparison, never private model reasoning."""

    revised_frame: Text
    disagreement: Text
    assumptions_reconsidered: list[Text] = Field(min_length=1)
    next_research_question: Text
    revision_trigger: Text
    evidence_refs: list[Text] = Field(min_length=1)
    reviewer_id: Text | None = None


class ClaimDraft(Record):
    """A proposed analyst claim; it cannot mutate the ledger directly."""

    local_id: Text
    statement: Text
    claim_type: ClaimType
    deliverable: Text
    evidence_refs: list[Text] = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    derived_from: list[Text]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    public_reasoning_summary: Text
    open_questions: list[str]


class AnalystResponse(Record):
    """The only claim-producing model contract in the default workflow."""

    role: Literal["analyst"]
    exercise_id: Text
    claims: list[ClaimDraft] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_claim_ids(self) -> Self:
        ids = [claim.local_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("Analyst response contains duplicate local IDs")
        return self


class PassageReference(Record):
    """A model-selected block ID within an explicitly assigned source snapshot."""

    source_id: Text
    passage_id: Text


class PassageClaimDraft(Record):
    """Model-facing draft, separate from the historical exact-citation contract."""

    local_id: Text
    statement: Text
    claim_type: ClaimType
    deliverable: Text
    evidence_refs: list[Text] = Field(min_length=1)
    citations: list[PassageReference] = Field(min_length=1)
    derived_from: list[Text]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    public_reasoning_summary: Text
    open_questions: list[str]


class PassageAnalystResponse(Record):
    """Wire output whose references Python resolves before canonical validation."""

    role: Literal["analyst"]
    exercise_id: Text
    claims: list[PassageClaimDraft] = Field(min_length=1, max_length=12)


class CritiqueIssue(Record):
    """A quality concern from the optional critic, not a competing claim."""

    claim_id: Text | None
    severity: Literal["info", "warning", "blocking"]
    category: Literal[
        "evidence",
        "scope",
        "logic",
        "missing_perspective",
        "premature_solution",
        "duplication",
    ]
    message: Text
    evidence_refs: list[Text]


class CriticResponse(Record):
    """A distinct audit contract used only when critique is requested."""

    role: Literal["critic"]
    exercise_id: Text
    recommendation: Literal["proceed", "review_carefully", "rerun"]
    issues: list[CritiqueIssue]
    next_action: Literal["review", "request_evidence"] = "review"
    next_question: str | None = None


class ModelSnapshot(Record):
    """Model and cost controls frozen into each run manifest."""

    name: Text
    reasoning_effort: (
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    timeout_seconds: float = Field(gt=0, le=300)
    max_retries: int = Field(ge=0, le=2)
    max_input_bytes: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    input_usd_per_million: str
    output_usd_per_million: str


class RunManifest(Record):
    """The complete, least-privilege context for one exercise run."""

    schema_version: Literal[2]
    run_id: Text
    created_at: datetime
    exercise_id: Text
    exercise_order: int = Field(gt=0)
    deliverables: list[Text] = Field(min_length=1)
    critic_enabled: bool
    selected_evidence_paths: list[Text]
    sources: list[FrozenSource] = Field(min_length=1)
    exercise_source: FrozenSource
    approved_context: list[ContextClaim]
    analyst_prompt: FrozenSource
    critic_prompt: FrozenSource | None
    model: ModelSnapshot
    ledger_path: Text
    human_frame: FrozenSource | None = None
    citation_format: Literal["line_spans", "passage_ids"] = "line_spans"


class LedgerClaim(Record):
    """A globally identified claim stored in the append-only ledger."""

    claim_id: Text
    run_id: Text
    local_id: Text
    exercise_id: Text
    agent_id: Literal["analyst", "human"] = "analyst"
    author_id: str | None = None
    statement: Text
    claim_type: ClaimType
    deliverable: Text
    evidence_refs: list[Text] = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    public_reasoning_summary: Text
    open_questions: list[str]


class Edge(Record):
    """A typed relationship between two ledger claims."""

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


class ReviewDecision(Record):
    """A human decision that is separate from evidentiary status."""

    decision: Literal["accepted", "rejected"]
    reviewer_id: Text
    public_reasoning_summary: Text


class StatusChange(Record):
    """An explicit evidence judgment; acceptance alone does not establish truth."""

    status: Status
    evidence_refs: list[Text] = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    public_reasoning_summary: Text


class RunSummary(Record):
    """Ledger marker for a fully reviewed exercise run."""

    claim_ids: list[Text] = Field(min_length=1)
    accepted_claim_ids: list[Text]


class EventBase(Record):
    """Shared metadata for event-sourced provenance."""

    event_id: Text
    ledger_id: Text
    timestamp: datetime
    run_id: Text
    exercise_id: Text
    subject_id: Text


class EvidenceAdded(EventBase):
    event_type: Literal["evidence_added"] = "evidence_added"
    payload: FrozenSource


class ClaimAdded(EventBase):
    event_type: Literal["claim_added"] = "claim_added"
    payload: LedgerClaim


class EdgeAdded(EventBase):
    event_type: Literal["edge_added"] = "edge_added"
    payload: Edge


class ReviewRecorded(EventBase):
    event_type: Literal["review_recorded"] = "review_recorded"
    payload: ReviewDecision


class StatusChanged(EventBase):
    event_type: Literal["status_changed"] = "status_changed"
    payload: StatusChange


class RunCompleted(EventBase):
    event_type: Literal["run_completed"] = "run_completed"
    payload: RunSummary


class ReviewCommit(Record):
    """Durable review identity used to recover receipts and reject altered retries."""

    review_id: Text
    review_sha256: Text
    review_kind: Literal["initial", "correction"]


class ReviewApplied(EventBase):
    event_type: Literal["review_applied"] = "review_applied"
    payload: ReviewCommit


class ReflectionRecorded(EventBase):
    event_type: Literal["reflection_recorded"] = "reflection_recorded"
    payload: ResearchReflection


class HumanFrameRecorded(EventBase):
    event_type: Literal["human_frame_recorded"] = "human_frame_recorded"
    payload: FrozenSource


LedgerEvent = Annotated[
    EvidenceAdded
    | ClaimAdded
    | EdgeAdded
    | ReviewRecorded
    | StatusChanged
    | RunCompleted
    | ReviewApplied
    | ReflectionRecorded
    | HumanFrameRecorded,
    Field(discriminator="event_type"),
]


class ClaimReview(Record):
    """Editable decision for one proposed claim."""

    local_id: Text
    decision: Literal["pending", "accept", "reject"] = "pending"
    validation_status: Status = "proposed"
    public_reasoning_summary: str = ""
    citations: list[EvidenceCitation] = Field(default_factory=list)
    revised_statement: Text | None = None
    revision_confidence: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )


class ReviewWorksheet(Record):
    """A human checkpoint bound to exact frozen run artifacts."""

    schema_version: Literal[2]
    review_id: Text
    run_id: Text
    run_directory: Text
    reviewer_id: Text
    manifest_sha256: Text
    response_sha256: Text
    critic_recommendation: str | None
    critic_issues: list[CritiqueIssue]
    decisions: list[ClaimReview] = Field(min_length=1)
    review_kind: Literal["initial", "correction"] = "initial"
    base_ledger_sha256: str = ""
    base_ledger_size: int = Field(default=0, ge=0)
    critic_sha256: str | None = None
    additional_sources: list[FrozenSource] = Field(default_factory=list)
    relations: list[Edge] = Field(default_factory=list)
    reflection: ResearchReflection | None = None


class ReviewBatch(Record):
    """Frozen commit intent; complete-line append interruptions can be resumed."""

    review_sha256: Text
    base_ledger_sha256: Text
    base_ledger_size: int = Field(ge=0)
    events: list[LedgerEvent] = Field(min_length=1)


class ReasoningAssessment(Record):
    """Human-assessed outcomes, kept distinct from mechanical run checks."""

    run_id: Text
    assessor_id: Text
    condition: Literal["human_only", "ai_first", "independent_comparison"]
    evidence_grounding: int = Field(ge=1, le=5)
    assumption_critique: int = Field(ge=1, le=5)
    contextual_explanation: int = Field(ge=1, le=5)
    investigation_value: int = Field(ge=1, le=5)
    rationale: Text
    unassisted_follow_up: str | None = None
    review_minutes: float | None = Field(default=None, ge=0)


class EvalReport(Record):
    """Deterministic run checks plus slots for human quality judgments."""

    schema_version: Literal[2]
    run_id: Text
    exercise_id: Text
    claim_count: int = Field(ge=0)
    assigned_evidence_count: int = Field(ge=0)
    cited_evidence_count: int = Field(ge=0)
    source_reference_validity: float = Field(ge=0, le=1)
    passage_accuracy: float | None
    deliverable_coverage: float = Field(ge=0, le=1)
    open_question_coverage: float = Field(ge=0, le=1)
    exact_duplicate_count: int = Field(ge=0)
    critic_enabled: bool
    critic_recommendation: str | None
    critic_issue_count: int = Field(ge=0)
    human_rubric: dict[str, int | None]
    independent_frame_recorded: bool
    reflection: ResearchReflection | None
    reasoning_assessment: ReasoningAssessment | None
    model_calls: int = Field(ge=0)
    reserved_usd: str


class LogEvent(Record):
    """Public operational trace; never stores hidden reasoning or credentials."""

    run_id: Text
    timestamp: datetime
    step: Text
    event_type: Text
    manifest_sha256: Text
    details: dict[str, JsonValue]
