"""Append and replay one run's JSONL history; intended for one local writer."""

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter

from .schemas import (
    Claim,
    ClaimAdded,
    Edge,
    EdgeAdded,
    Evidence,
    EvidenceAdded,
    GraphEvent,
    Review,
    ReviewRecorded,
    Status,
    StatusChanged,
)

EVENT_ADAPTER = TypeAdapter(GraphEvent)


@dataclass
class GraphState:
    """Derived state, rebuilt from history rather than saved over old records."""

    run_id: str | None = None
    event_ids: set[str] = field(default_factory=set)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    statuses: dict[str, Status] = field(default_factory=dict)
    reviews: dict[str, Review] = field(default_factory=dict)

    def apply(self, event: GraphEvent) -> None:
        """Validate references and transitions before changing derived state."""
        if event.event_id in self.event_ids:
            raise ValueError(f"Duplicate event ID: {event.event_id}")
        if self.run_id is not None and self.run_id != event.run_id:
            raise ValueError(f"Run {event.run_id} cannot enter graph for {self.run_id}")
        payload = event.payload
        subject = event.subject_id
        if isinstance(event, (EvidenceAdded, ClaimAdded, EdgeAdded)):
            if (
                subject in self.evidence
                or subject in self.claims
                or subject in self.edges
            ):
                raise ValueError(f"Duplicate graph subject ID: {subject}")
        if isinstance(event, (ClaimAdded, StatusChanged)):
            for source in payload.evidence_refs:
                if source not in self.evidence:
                    raise ValueError(f"Claim {subject}: unknown evidence {source}")
        if isinstance(event, EvidenceAdded):
            if subject != payload.source_id:
                raise ValueError(f"Evidence subject {subject} does not match source ID")
            self.evidence[subject] = payload
        elif isinstance(event, ClaimAdded):
            if (
                subject != payload.takeaway_id
                or event.exercise_id != payload.exercise_id
            ):
                raise ValueError(f"Claim {subject}: ID or exercise origin mismatch")
            if payload.validation_status != "proposed":
                raise ValueError(f"Claim {subject} must start as proposed")
            self.claims[subject] = payload
            self.statuses[subject] = "proposed"
            self.reviews[subject] = "pending"
        elif isinstance(event, EdgeAdded):
            for claim_id in (payload.source_id, payload.target_id):
                if claim_id not in self.claims:
                    raise ValueError(f"Edge {subject}: unknown claim {claim_id}")
            if payload.source_id == payload.target_id:
                raise ValueError(f"Edge {subject}: self-relations are not allowed")
            if payload.relation in {"invalidates", "supersedes"}:
                if self.statuses[payload.source_id] != "supported":
                    raise ValueError(
                        f"Edge {subject}: replacement claim must be supported"
                    )
            self.edges[subject] = payload
        elif isinstance(event, (StatusChanged, ReviewRecorded)):
            if subject not in self.claims:
                raise ValueError(f"Unknown claim: {subject}")
            if isinstance(event, ReviewRecorded):
                self.reviews[subject] = payload.decision
            else:
                old_status = self.statuses[subject]
                if old_status == "deprecated" or payload.status in {
                    old_status,
                    "proposed",
                }:
                    raise ValueError(
                        f"Claim {subject}: invalid status transition "
                        f"{old_status} -> {payload.status}"
                    )
                if payload.status == "deprecated" and not any(
                    edge.target_id == subject
                    and edge.relation in {"invalidates", "supersedes"}
                    for edge in self.edges.values()
                ):
                    raise ValueError(
                        f"Claim {subject}: deprecation requires invalidation edge"
                    )
                if payload.status == "accepted_tension" and not any(
                    subject in (edge.source_id, edge.target_id)
                    and edge.relation == "contradicts"
                    for edge in self.edges.values()
                ):
                    raise ValueError(
                        f"Claim {subject}: tension requires contradiction edge"
                    )
                self.statuses[subject] = payload.status
        self.run_id = event.run_id
        self.event_ids.add(event.event_id)

    def reportable_claims(self) -> list[Claim]:
        """Return reviewed supported claims/tensions, never invalidated targets.

        Eligibility is structural, not proof of truth. Reports must still retain
        claim type, uncertainty, and opposing claims for accepted tensions.
        """
        invalidated = {
            edge.target_id
            for edge in self.edges.values()
            if edge.relation in {"invalidates", "supersedes"}
        }
        # A derived conclusion cannot outlive a dependency it explicitly requires.
        # depends_on points from conclusion to premise; supports points the other way.
        while True:
            blocked = (
                invalidated
                | {
                    edge.source_id
                    for edge in self.edges.values()
                    if edge.relation == "depends_on" and edge.target_id in invalidated
                }
                | {
                    edge.target_id
                    for edge in self.edges.values()
                    if edge.relation == "supports" and edge.source_id in invalidated
                }
            )
            if blocked == invalidated:
                break
            invalidated = blocked
        return [
            claim
            for claim_id, claim in self.claims.items()
            if self.statuses[claim_id] in {"supported", "accepted_tension"}
            and self.reviews[claim_id] == "accepted"
            and claim_id not in invalidated
        ]


def replay(path: Path) -> GraphState:
    """Validate history and derive current state; absent history is empty."""
    state = GraphState()
    if not path.exists():
        return state
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        raise ValueError(f"{path}: incomplete final record; history was not modified")
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            state.apply(EVENT_ADAPTER.validate_json(line))
        except ValueError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
    return state


def append_events(path: Path, events: list[GraphEvent]) -> GraphState:
    """Validate a full batch before appending; never truncate existing history.

    Not a concurrent or transactional database. Interrupted writes are detected
    on replay; automatic repair and concurrent writers are deliberately unsupported.
    """
    state = replay(path)
    for event in events:
        state.apply(EVENT_ADAPTER.validate_json(event.model_dump_json()))
    if events:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("".join(event.model_dump_json() + "\n" for event in events))
    return state
