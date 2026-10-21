"""Append-only, single-writer provenance ledger with deterministic replay."""

import os
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

from pydantic import TypeAdapter

from .schemas import (
    ClaimAdded,
    ContextClaim,
    Edge,
    EdgeAdded,
    EvidenceAdded,
    FrozenSource,
    HumanFrameRecorded,
    LedgerClaim,
    LedgerEvent,
    ReflectionRecorded,
    ResearchReflection,
    ReviewApplied,
    ReviewCommit,
    ReviewRecorded,
    RunCompleted,
    Status,
    StatusChange,
    StatusChanged,
)
from .sources import validate_citations

EVENT_ADAPTER = TypeAdapter(LedgerEvent)


@dataclass
class GraphState:
    """Current state derived exclusively from immutable ledger events."""

    ledger_id: str | None = None
    event_ids: set[str] = field(default_factory=set)
    evidence: dict[str, FrozenSource] = field(default_factory=dict)
    claims: dict[str, LedgerClaim] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    reviews: dict[str, str] = field(default_factory=dict)
    statuses: dict[str, Status] = field(default_factory=dict)
    completed_runs: set[str] = field(default_factory=set)
    applied_reviews: dict[str, ReviewCommit] = field(default_factory=dict)
    validations: dict[str, StatusChange] = field(default_factory=dict)
    reflections: dict[str, ResearchReflection] = field(default_factory=dict)
    human_frames: dict[str, FrozenSource] = field(default_factory=dict)

    def apply(self, event: LedgerEvent) -> None:
        """Validate one event before changing derived state."""
        if event.event_id in self.event_ids:
            raise ValueError(f"Duplicate event ID: {event.event_id}")
        if self.ledger_id is not None and event.ledger_id != self.ledger_id:
            raise ValueError("Cannot mix events from different ledgers")

        subject = event.subject_id
        if isinstance(event, EvidenceAdded):
            if subject != event.payload.source_id:
                raise ValueError("Evidence subject must match its source ID")
            if subject in self.evidence:
                raise ValueError(f"Duplicate evidence ID: {subject}")
            self.evidence[subject] = event.payload
        elif isinstance(event, ClaimAdded):
            claim = event.payload
            if subject != claim.claim_id or event.run_id != claim.run_id:
                raise ValueError("Claim event identity mismatch")
            if subject in self.claims:
                raise ValueError(f"Duplicate claim ID: {subject}")
            unknown = set(claim.evidence_refs) - set(self.evidence)
            if unknown:
                raise ValueError(f"Claim {subject}: unknown evidence {sorted(unknown)}")
            validate_citations(claim.citations, self.evidence)
            self.claims[subject] = claim
            self.reviews[subject] = "pending"
            self.statuses[subject] = "proposed"
        elif isinstance(event, EdgeAdded):
            edge = event.payload
            if subject in self.edges:
                raise ValueError(f"Duplicate edge ID: {subject}")
            if edge.source_id == edge.target_id:
                raise ValueError("Self-relations are not allowed")
            unknown = {edge.source_id, edge.target_id} - set(self.claims)
            if unknown:
                raise ValueError(f"Edge {subject}: unknown claims {sorted(unknown)}")
            if edge.relation in {"invalidates", "supersedes"} and (
                self.statuses[edge.source_id] != "supported"
                or self.reviews[edge.source_id] != "accepted"
            ):
                raise ValueError("Invalidation requires an accepted supported claim")
            if edge.relation == "depends_on":
                dependencies = {}
                for item in [*self.edges.values(), edge]:
                    if item.relation == "depends_on":
                        dependencies.setdefault(item.source_id, set()).add(
                            item.target_id
                        )
                tuple(TopologicalSorter(dependencies).static_order())
            self.edges[subject] = edge
        elif isinstance(event, ReviewRecorded):
            if subject not in self.claims:
                raise ValueError(f"Unknown reviewed claim: {subject}")
            self.reviews[subject] = event.payload.decision
        elif isinstance(event, StatusChanged):
            if subject not in self.claims:
                raise ValueError(f"Unknown status claim: {subject}")
            status = event.payload.status
            if status in {"supported", "accepted_tension"} and (
                self.reviews[subject] != "accepted"
            ):
                raise ValueError("Only an accepted claim can change evidence status")
            if self.statuses[subject] == "deprecated" and status != "deprecated":
                raise ValueError("Deprecated claims cannot be revived; add a new claim")
            unknown = set(event.payload.evidence_refs) - set(self.evidence)
            if unknown:
                raise ValueError(
                    f"Status change uses unknown evidence {sorted(unknown)}"
                )
            validate_citations(event.payload.citations, self.evidence)
            if event.payload.citations and {
                citation.source_id for citation in event.payload.citations
            } != set(event.payload.evidence_refs):
                raise ValueError(
                    "Validation passages must cover its evidence references"
                )
            if status == "accepted_tension" and not any(
                subject in {edge.source_id, edge.target_id}
                and edge.relation == "contradicts"
                for edge in self.edges.values()
            ):
                raise ValueError("Accepted tension requires a contradiction edge")
            if status == "deprecated" and not any(
                edge.target_id == subject
                and edge.relation in {"invalidates", "supersedes"}
                for edge in self.edges.values()
            ):
                raise ValueError(
                    "Deprecation requires an invalidation or supersession edge"
                )
            self.statuses[subject] = status
            self.validations[subject] = event.payload
        elif isinstance(event, RunCompleted):
            if event.run_id in self.completed_runs:
                raise ValueError(f"Run already completed: {event.run_id}")
            if set(event.payload.claim_ids) - set(self.claims):
                raise ValueError("Completed run references unknown claims")
            if set(event.payload.accepted_claim_ids) - set(event.payload.claim_ids):
                raise ValueError("Accepted claims must belong to the completed run")
            if any(
                self.claims[key].run_id != event.run_id
                or self.reviews[key] == "pending"
                for key in event.payload.claim_ids
            ):
                raise ValueError("Completion requires reviewed claims from this run")
            if set(event.payload.accepted_claim_ids) != {
                key
                for key in event.payload.claim_ids
                if self.reviews[key] == "accepted"
            }:
                raise ValueError(
                    "Completion acceptance does not match recorded reviews"
                )
            self.completed_runs.add(event.run_id)
        elif isinstance(event, ReviewApplied):
            review = event.payload
            if review.review_id in self.applied_reviews:
                raise ValueError(f"Review already applied: {review.review_id}")
            if event.run_id not in self.completed_runs:
                raise ValueError("Review commit requires a completed run")
            self.applied_reviews[review.review_id] = review
        elif isinstance(event, ReflectionRecorded):
            unknown = set(event.payload.evidence_refs) - set(self.evidence)
            if unknown:
                raise ValueError(
                    f"Reflection cites unknown evidence: {sorted(unknown)}"
                )
            self.reflections[event.run_id] = event.payload
        elif isinstance(event, HumanFrameRecorded):
            if event.run_id in self.human_frames:
                raise ValueError(
                    "Independent human frame is already recorded for this run"
                )
            self.human_frames[event.run_id] = event.payload

        self.ledger_id = event.ledger_id
        self.event_ids.add(event.event_id)

    def blocked_claim_ids(self, require_supported: bool = False) -> set[str]:
        """Propagate invalid premises; final reports also require supported premises."""
        blocked = {
            key
            for key in self.claims
            if self.reviews[key] != "accepted"
            or self.statuses[key] in {"contested", "deprecated"}
            or (
                require_supported
                and self.statuses[key] not in {"supported", "accepted_tension"}
            )
        }
        blocked.update(
            edge.target_id
            for edge in self.edges.values()
            if edge.relation in {"invalidates", "supersedes"}
        )
        while True:
            dependents = {
                edge.source_id
                for edge in self.edges.values()
                if edge.relation == "depends_on" and edge.target_id in blocked
            } | {
                edge.target_id
                for edge in self.edges.values()
                if edge.relation == "supports" and edge.source_id in blocked
            }
            if dependents <= blocked:
                return blocked
            blocked.update(dependents)

    def context_claims(self) -> list[ContextClaim]:
        """Return reviewed claims safe to expose to a later exercise."""
        blocked = self.blocked_claim_ids()
        return [
            ContextClaim(
                claim_id=claim_id,
                exercise_id=claim.exercise_id,
                statement=claim.statement,
                claim_type=claim.claim_type,
                evidence_refs=list(
                    dict.fromkeys(
                        claim.evidence_refs
                        + (
                            self.validations[claim_id].evidence_refs
                            if claim_id in self.validations
                            else []
                        )
                    )
                ),
                status=self.statuses[claim_id],
            )
            for claim_id, claim in self.claims.items()
            if claim_id not in blocked
        ]

    def reportable_claims(self) -> list[LedgerClaim]:
        """Return human-accepted claims with affirmative evidence status."""
        blocked = self.blocked_claim_ids(require_supported=True)
        while True:
            incomplete = (
                {
                    key
                    for key in self.claims
                    if self.statuses[key] == "accepted_tension"
                    and any(
                        edge.relation == "contradicts"
                        and key in {edge.source_id, edge.target_id}
                        and bool({edge.source_id, edge.target_id} & blocked)
                        for edge in self.edges.values()
                    )
                }
                | {
                    edge.source_id
                    for edge in self.edges.values()
                    if edge.relation == "depends_on" and edge.target_id in blocked
                }
                | {
                    edge.target_id
                    for edge in self.edges.values()
                    if edge.relation == "supports" and edge.source_id in blocked
                }
            )
            if incomplete <= blocked:
                break
            blocked.update(incomplete)
        return [
            claim for claim_id, claim in self.claims.items() if claim_id not in blocked
        ]


def replay(path: Path) -> GraphState:
    """Validate every record and derive ledger state without rewriting history."""
    state = GraphState()
    if not path.exists():
        return state
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        raise ValueError(f"{path}: incomplete final record")
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            state.apply(EVENT_ADAPTER.validate_json(line))
        except ValueError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
    return state


def append_events(path: Path, events: list[LedgerEvent]) -> GraphState:
    """Validate a complete batch, then append it without truncating history."""
    state = replay(path)
    for event in events:
        state.apply(EVENT_ADAPTER.validate_python(event))
    if events:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("".join(event.model_dump_json() + "\n" for event in events))
            stream.flush()
            os.fsync(stream.fileno())
    return state
