"""Repeatable structural evaluation for saved version 2 runs."""

import json
from decimal import Decimal
from pathlib import Path

import yaml

from .graph import replay
from .review import load_completed_run
from .schemas import EvalReport, ReasoningAssessment
from .sources import validate_citations


def evaluate_run(
    run_directory: Path, output: Path, assessment_path: Path | None = None
) -> Path:
    """Score deterministic invariants and emit a human quality-rubric scaffold."""
    run_directory = run_directory.resolve()
    manifest, response, critique = load_completed_run(run_directory)
    assessment = (
        ReasoningAssessment.model_validate(
            yaml.safe_load(assessment_path.read_text(encoding="utf-8"))
        )
        if assessment_path is not None
        else None
    )
    if assessment is not None and assessment.run_id != manifest.run_id:
        raise ValueError("Reasoning assessment belongs to a different run")
    if (
        assessment is not None
        and assessment.condition == "independent_comparison"
        and manifest.human_frame is None
    ):
        raise ValueError("Independent comparison requires a pre-model human frame")
    assigned = {source.source_id for source in manifest.sources}
    citations = [ref for claim in response.claims for ref in claim.evidence_refs]
    covered = {claim.deliverable for claim in response.claims}
    passages = [citation for claim in response.claims for citation in claim.citations]
    sources = {source.source_id: source for source in manifest.sources}
    exact_passages = 0
    for citation in passages:
        try:
            validate_citations([citation], sources)
        except (KeyError, ValueError):
            continue
        exact_passages += 1
    logs = [
        json.loads(line)
        for line in (run_directory / "run_events.jsonl").read_text().splitlines()
    ]
    normalized = [
        " ".join(claim.statement.lower().split()) for claim in response.claims
    ]
    report = EvalReport(
        schema_version=2,
        run_id=manifest.run_id,
        exercise_id=manifest.exercise_id,
        claim_count=len(response.claims),
        assigned_evidence_count=len(assigned),
        cited_evidence_count=len(set(citations)),
        source_reference_validity=(
            sum(ref in assigned for ref in citations) / len(citations)
            if citations
            else 0
        ),
        passage_accuracy=exact_passages / len(passages) if passages else None,
        deliverable_coverage=len(covered & set(manifest.deliverables))
        / len(manifest.deliverables),
        open_question_coverage=sum(
            bool(claim.open_questions) for claim in response.claims
        )
        / len(response.claims),
        exact_duplicate_count=len(normalized) - len(set(normalized)),
        critic_enabled=manifest.critic_enabled,
        critic_recommendation=critique.recommendation if critique else None,
        critic_issue_count=len(critique.issues) if critique else 0,
        human_rubric={
            "evidence_grounding_1_to_5": None,
            "useful_coverage_1_to_5": None,
            "non_redundancy_1_to_5": None,
            "uncertainty_handling_1_to_5": None,
            "next_action_value_1_to_5": None,
        },
        independent_frame_recorded=manifest.human_frame is not None,
        reflection=replay(Path(manifest.ledger_path)).reflections.get(manifest.run_id),
        reasoning_assessment=assessment,
        model_calls=sum(event["event_type"] == "attempt_started" for event in logs),
        reserved_usd=str(
            sum(
                (
                    Decimal(event["details"]["reserved_usd"])
                    for event in logs
                    if event["event_type"] == "budget_checked"
                    and event["details"].get("reservation_accepted")
                ),
                Decimal(0),
            )
        ),
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError(f"Eval output already exists: {output}")
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output
