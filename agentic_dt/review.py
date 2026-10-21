"""Human comparison, correction, and recoverable append-only review commits."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from .graph import EVENT_ADAPTER, append_events, replay
from .inquiry import write_comparison
from .schemas import (
    AnalystResponse,
    CriticResponse,
    LedgerClaim,
    ReviewBatch,
    ReviewWorksheet,
    RunManifest,
)
from .sources import file_sha256, freeze_source, validate_citations

LEDGER_ID = "agentic-reframe-v2"


def load_completed_run(
    directory: Path,
) -> tuple[RunManifest, AnalystResponse, CriticResponse | None]:
    """Verify frozen inputs and checkpointed responses before downstream use."""
    manifest_path = directory / "input_manifest.json"
    manifest = RunManifest.model_validate_json(manifest_path.read_bytes())
    logs = [
        json.loads(line)
        for line in (directory / "run_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    digest = file_sha256(manifest_path)
    if not logs or any(event["manifest_sha256"] != digest for event in logs):
        raise ValueError("Run manifest is not bound to its execution log")
    for role in ("analyst", "critic") if manifest.critic_enabled else ("analyst",):
        saved = [
            event
            for event in logs
            if event["event_type"] == "response_saved" and event["step"] == role
        ]
        if (
            not saved
            or file_sha256(directory / f"{role}_response.json")
            != (saved[-1]["details"]["sha256"])
        ):
            raise ValueError(f"{role}: response does not match its checkpoint")
    analysis = AnalystResponse.model_validate_json(
        (directory / "analyst_response.json").read_bytes()
    )
    critique = (
        CriticResponse.model_validate_json(
            (directory / "critic_response.json").read_bytes()
        )
        if manifest.critic_enabled
        else None
    )
    return manifest, analysis, critique


def export_review(
    run_directory: Path,
    output: Path,
    reviewer: str,
    evidence_paths: list[Path] | None = None,
) -> Path:
    """Export decisions and a comparison packet, including correction reviews."""
    run_directory = run_directory.resolve()
    manifest, response, critique = load_completed_run(run_directory)
    status = json.loads((run_directory / "status.json").read_text(encoding="utf-8"))
    if status["state"] not in {"awaiting_review", "completed"}:
        raise ValueError("Resume the run before exporting a review")
    ledger_path = Path(manifest.ledger_path)
    raw = ledger_path.read_bytes() if ledger_path.exists() else b""
    state = replay(ledger_path)
    correction = manifest.run_id in state.completed_runs
    additional_sources = []
    for path in evidence_paths or []:
        source = freeze_source(path, "review-evidence", manifest.model.max_input_bytes)
        additional_sources.append(
            source.model_copy(
                update={
                    "source_id": (
                        f"review-evidence:{path.stem}:{source.content_sha256[:12]}"
                    )
                }
            )
        )
    worksheet = ReviewWorksheet(
        schema_version=2,
        review_id=f"review-{uuid4().hex}",
        run_id=manifest.run_id,
        run_directory=str(run_directory),
        reviewer_id=reviewer,
        manifest_sha256=file_sha256(run_directory / "input_manifest.json"),
        response_sha256=file_sha256(run_directory / "analyst_response.json"),
        critic_recommendation=critique.recommendation if critique else None,
        critic_issues=critique.issues if critique else [],
        critic_sha256=(
            file_sha256(run_directory / "critic_response.json") if critique else None
        ),
        review_kind="correction" if correction else "initial",
        base_ledger_sha256=hashlib.sha256(raw).hexdigest(),
        base_ledger_size=len(raw),
        additional_sources=additional_sources,
        decisions=[
            {
                "local_id": claim.local_id,
                "validation_status": state.statuses.get(
                    f"{manifest.run_id}:{claim.local_id}", "proposed"
                ),
                "citations": claim.citations,
            }
            for claim in response.claims
        ],
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = worksheet.model_dump(mode="json")
    if manifest.human_frame is not None:
        data["reflection"] = {
            "revised_frame": "",
            "disagreement": "",
            "assumptions_reconsidered": [],
            "next_research_question": "",
            "revision_trigger": "",
            "evidence_refs": [],
        }
    with output.open("x", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
    write_comparison(
        manifest, response, critique, output.with_suffix(".md"), additional_sources
    )
    return output


def apply_review(review_path: Path) -> Path:
    """Commit a frozen batch, resume partial appends, and rebuild receipts."""
    review_path = review_path.resolve()
    worksheet = ReviewWorksheet.model_validate(
        yaml.safe_load(review_path.read_text(encoding="utf-8"))
    )
    review_hash = file_sha256(review_path)
    if any(item.decision == "pending" for item in worksheet.decisions):
        raise ValueError("Every claim requires an accept or reject decision")
    ids = [item.local_id for item in worksheet.decisions]
    if len(ids) != len(set(ids)):
        raise ValueError("Review contains duplicate claim decisions")
    directory = Path(worksheet.run_directory)
    manifest, response, critique = load_completed_run(directory)
    if file_sha256(directory / "input_manifest.json") != worksheet.manifest_sha256:
        raise ValueError("Run manifest changed after review export")
    if file_sha256(directory / "analyst_response.json") != worksheet.response_sha256:
        raise ValueError("Analyst response changed after review export")
    critic_hash = file_sha256(directory / "critic_response.json") if critique else None
    if critic_hash != worksheet.critic_sha256:
        raise ValueError("Critic response changed after review export")
    if worksheet.run_id != manifest.run_id:
        raise ValueError("Review belongs to a different run")
    if set(ids) != {claim.local_id for claim in response.claims}:
        raise ValueError("Review must decide every analyst claim exactly once")
    if manifest.human_frame is not None and worksheet.reflection is None:
        raise ValueError("Record your comparison and research decision in reflection")

    ledger_path = Path(manifest.ledger_path)
    raw = ledger_path.read_bytes() if ledger_path.exists() else b""
    state = replay(ledger_path)
    committed = state.applied_reviews.get(worksheet.review_id)
    if committed is not None and committed.review_sha256 != review_hash:
        raise ValueError("Applied review changed; export a fresh correction worksheet")
    batch_path = review_path.with_suffix(".batch.json")
    receipt_path = review_path.with_suffix(".receipt.json")
    if batch_path.exists():
        batch = ReviewBatch.model_validate_json(batch_path.read_bytes())
        if batch.review_sha256 != review_hash:
            raise ValueError("Prepared review changed; export a fresh worksheet")
    elif committed is not None:
        raise ValueError(
            f"Committed review is missing its recovery batch: {batch_path}"
        )
    else:
        if len(raw) != worksheet.base_ledger_size or (
            hashlib.sha256(raw).hexdigest() != worksheet.base_ledger_sha256
        ):
            raise ValueError(
                "Ledger changed after review export; export a fresh review"
            )
        if (manifest.run_id in state.completed_runs) != (
            worksheet.review_kind == "correction"
        ):
            raise ValueError(
                "Use a fresh correction review for an already recorded run"
            )
        sources = dict(state.evidence)
        for source in [*manifest.sources, *worksheet.additional_sources]:
            if source.source_id in sources and sources[source.source_id] != source:
                raise ValueError(f"Evidence ID collision: {source.source_id}")
            sources[source.source_id] = source
        events = []
        timestamp = datetime.now(timezone.utc)

        def add(event_type: str, subject: str, payload: dict) -> None:
            events.append(
                EVENT_ADAPTER.validate_python(
                    {
                        "event_id": f"{worksheet.review_id}:{len(events) + 1}",
                        "ledger_id": state.ledger_id or LEDGER_ID,
                        "timestamp": timestamp,
                        "run_id": manifest.run_id,
                        "exercise_id": manifest.exercise_id,
                        "subject_id": subject,
                        "event_type": event_type,
                        "payload": payload,
                    }
                )
            )

        for source in [*manifest.sources, *worksheet.additional_sources]:
            if source.source_id in state.evidence:
                if state.evidence[source.source_id] != source:
                    raise ValueError(f"Evidence ID collision: {source.source_id}")
            elif not any(
                event.event_type == "evidence_added"
                and event.subject_id == source.source_id
                for event in events
            ):
                add("evidence_added", source.source_id, source.model_dump())

        originals = {
            claim.local_id: f"{manifest.run_id}:{claim.local_id}"
            for claim in response.claims
        }
        all_ids = list(originals.values())
        if worksheet.review_kind == "initial":
            if manifest.human_frame is not None:
                add(
                    "human_frame_recorded",
                    f"{manifest.run_id}:human-frame",
                    manifest.human_frame.model_dump(),
                )
            for claim in response.claims:
                add(
                    "claim_added",
                    originals[claim.local_id],
                    LedgerClaim(
                        claim_id=originals[claim.local_id],
                        run_id=manifest.run_id,
                        local_id=claim.local_id,
                        exercise_id=manifest.exercise_id,
                        **claim.model_dump(exclude={"local_id", "derived_from"}),
                    ).model_dump(),
                )
                for premise in dict.fromkeys(claim.derived_from):
                    if premise in state.blocked_claim_ids():
                        raise ValueError(
                            f"Required premise is no longer usable: {premise}"
                        )
                    add(
                        "edge_added",
                        f"{worksheet.review_id}:dependency:{len(events)}",
                        {
                            "source_id": originals[claim.local_id],
                            "target_id": premise,
                            "relation": "depends_on",
                            "public_reasoning_summary": claim.public_reasoning_summary,
                        },
                    )

        decisions = {item.local_id: item for item in worksheet.decisions}
        accepted = []
        deferred_statuses = []
        for claim in response.claims:
            decision = decisions[claim.local_id]
            claim_id = originals[claim.local_id]
            citations = decision.citations or claim.citations
            validate_citations(citations, sources)
            if decision.validation_status != "proposed" and (
                not citations or not decision.public_reasoning_summary.strip()
            ):
                raise ValueError(
                    f"{claim.local_id}: evidence status requires passages "
                    "and a rationale"
                )
            if decision.revised_statement is not None and decision.decision != "accept":
                raise ValueError("A revised statement requires an accept decision")
            add(
                "review_recorded",
                claim_id,
                {
                    "decision": (
                        "accepted"
                        if decision.decision == "accept"
                        and decision.revised_statement is None
                        else "rejected"
                    ),
                    "reviewer_id": worksheet.reviewer_id,
                    "public_reasoning_summary": decision.public_reasoning_summary
                    or f"Human review: {decision.decision}.",
                },
            )
            if decision.revised_statement is not None:
                if decision.revision_confidence is None:
                    raise ValueError("A human revision requires revision_confidence")
                revised_id = (
                    f"{manifest.run_id}:human:{worksheet.review_id}:{claim.local_id}"
                )
                add(
                    "claim_added",
                    revised_id,
                    LedgerClaim(
                        claim_id=revised_id,
                        run_id=manifest.run_id,
                        local_id=claim.local_id,
                        exercise_id=manifest.exercise_id,
                        agent_id="human",
                        author_id=worksheet.reviewer_id,
                        statement=decision.revised_statement,
                        claim_type="hypothesis",
                        deliverable=claim.deliverable,
                        evidence_refs=list(
                            dict.fromkeys(c.source_id for c in citations)
                        )
                        or claim.evidence_refs,
                        citations=citations,
                        confidence=decision.revision_confidence,
                        public_reasoning_summary=decision.public_reasoning_summary
                        or "Human revision of the proposed interpretation.",
                        open_questions=claim.open_questions,
                    ).model_dump(),
                )
                add(
                    "edge_added",
                    f"{revised_id}:refines",
                    {
                        "source_id": revised_id,
                        "target_id": claim_id,
                        "relation": "refines",
                        "public_reasoning_summary": (
                            "Human-authored revision; original retained."
                        ),
                    },
                )
                # A wording change cannot silently erase required premises.
                premises = set(claim.derived_from) | {
                    edge.target_id
                    for edge in state.edges.values()
                    if edge.source_id == claim_id and edge.relation == "depends_on"
                }
                for premise in sorted(premises):
                    add(
                        "edge_added",
                        f"{revised_id}:dependency:{len(events)}",
                        {
                            "source_id": revised_id,
                            "target_id": premise,
                            "relation": "depends_on",
                            "public_reasoning_summary": (
                                "Preserve the original claim's required premise."
                            ),
                        },
                    )
                add(
                    "review_recorded",
                    revised_id,
                    {
                        "decision": "accepted",
                        "reviewer_id": worksheet.reviewer_id,
                        "public_reasoning_summary": decision.public_reasoning_summary
                        or "Accept the human revision for inquiry.",
                    },
                )
                claim_id = revised_id
                all_ids.append(revised_id)
            if decision.decision == "accept":
                accepted.append(claim_id)
            current_status = state.statuses.get(claim_id, "proposed")
            if (
                decision.validation_status != current_status
                or decision.public_reasoning_summary.strip()
            ):
                status_payload = {
                    "status": decision.validation_status,
                    "evidence_refs": list(dict.fromkeys(c.source_id for c in citations))
                    or claim.evidence_refs,
                    "citations": [citation.model_dump() for citation in citations],
                    "public_reasoning_summary": decision.public_reasoning_summary
                    or "Human evidence-status judgment.",
                }
                if decision.validation_status in {"deprecated", "accepted_tension"}:
                    deferred_statuses.append((claim_id, status_payload))
                else:
                    add("status_changed", claim_id, status_payload)

        for index, relation in enumerate(worksheet.relations):
            add(
                "edge_added",
                f"{worksheet.review_id}:relation:{index}",
                relation.model_dump(),
            )
        for claim_id, status_payload in deferred_statuses:
            add("status_changed", claim_id, status_payload)
        if worksheet.reflection is not None:
            add(
                "reflection_recorded",
                f"{worksheet.review_id}:reflection",
                worksheet.reflection.model_copy(
                    update={"reviewer_id": worksheet.reviewer_id}
                ).model_dump(),
            )
        if worksheet.review_kind == "initial":
            add(
                "run_completed",
                f"{manifest.run_id}:completed",
                {
                    "claim_ids": all_ids,
                    "accepted_claim_ids": accepted,
                },
            )
        add(
            "review_applied",
            worksheet.review_id,
            {
                "review_id": worksheet.review_id,
                "review_sha256": review_hash,
                "review_kind": worksheet.review_kind,
            },
        )
        batch = ReviewBatch(
            review_sha256=review_hash,
            base_ledger_sha256=worksheet.base_ledger_sha256,
            base_ledger_size=worksheet.base_ledger_size,
            events=events,
        )
        # Validate the entire proposed commit before persisting any intent or event.
        for event in events:
            state.apply(event)
        with batch_path.open("x", encoding="utf-8") as stream:
            stream.write(batch.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())

    if committed is None:
        if hashlib.sha256(raw[: batch.base_ledger_size]).hexdigest() != (
            batch.base_ledger_sha256
        ):
            raise ValueError("Review's base ledger history changed")
        suffix = raw[batch.base_ledger_size :]
        written = [EVENT_ADAPTER.validate_json(line) for line in suffix.splitlines()]
        if written != batch.events[: len(written)]:
            raise ValueError(
                "Ledger contains unrelated events after this review's base"
            )
        append_events(ledger_path, batch.events[len(written) :])

    receipt = {
        "schema_version": 2,
        "review_id": worksheet.review_id,
        "run_id": manifest.run_id,
        "review_sha256": review_hash,
        "ledger_path": str(ledger_path),
        "ledger_sha256": file_sha256(ledger_path),
        "event_ids": [event.event_id for event in batch.events],
    }
    temporary_receipt = receipt_path.with_suffix(".json.tmp")
    temporary_receipt.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temporary_receipt.replace(receipt_path)
    (directory / "status.json").write_text(
        json.dumps({"state": "completed", "run_id": manifest.run_id}, indent=2),
        encoding="utf-8",
    )
    return receipt_path
