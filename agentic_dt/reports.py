"""Deterministic compilation from reviewed, evidence-qualified ledger claims."""

import hashlib
import json
from pathlib import Path

from .graph import replay

SECTIONS = {
    "Framed challenge": {"frame_challenge", "align_impact_goals"},
    "Audiences and participation": {
        "align_participatory_approach",
        "power_mapping",
        "extremes_and_mainstreams",
    },
    "Stakeholder jobs, pains, and gains": {
        "interviews",
        "value_proposition_canvas",
    },
    "Landscape and constraints": {
        "secondary_research",
        "resource_flow",
        "photojournal",
    },
    "Opportunity reframings": {
        "frame_challenge",
        "analogous_inspiration",
        "five_whys",
    },
    "Later-phase project plan": {
        "align_impact_goals",
        "align_participatory_approach",
        "project_plan",
    },
}


def compile_reports(ledger_path: Path, output: Path) -> Path:
    """Create an immutable report snapshot without model calls or graph writes."""
    ledger_path = ledger_path.resolve()
    raw = ledger_path.read_bytes()
    state = replay(ledger_path)
    if not state.claims:
        raise ValueError("Compilation requires at least one reviewed claim")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(raw).hexdigest()
    reportable = {claim.claim_id for claim in state.reportable_claims()}

    index = {
        "schema_version": 2,
        "ledger_path": str(ledger_path),
        "ledger_sha256": digest,
        "claims": [
            {
                **claim.model_dump(),
                "review": state.reviews[claim_id],
                "status": state.statuses[claim_id],
                "reportable": claim_id in reportable,
                "blocked": claim_id in state.blocked_claim_ids(require_supported=True),
                "validation": (
                    state.validations[claim_id].model_dump()
                    if claim_id in state.validations
                    else None
                ),
            }
            for claim_id, claim in state.claims.items()
        ],
        "edges": [
            {"edge_id": edge_id, **edge.model_dump()}
            for edge_id, edge in state.edges.items()
        ],
        "evidence": [source.model_dump() for source in state.evidence.values()],
        "completed_runs": sorted(state.completed_runs),
        "human_frames": {
            key: source.model_dump() for key, source in state.human_frames.items()
        },
        "researcher_reflections": {
            key: reflection.model_dump()
            for key, reflection in state.reflections.items()
        },
    }
    (output / "synthesis_index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )

    lines = [
        "# Design research brief",
        "",
        f"Ledger SHA-256: `{digest}`",
        "",
        "Factual sections contain only human-accepted, evidence-supported claims. "
        "Human framing decisions are labeled separately. This is a framing "
        "artifact, not a validated solution proposal.",
        "",
    ]
    if state.reflections:
        lines.extend(["## Human framing decisions", ""])
        for run_id, reflection in state.reflections.items():
            lines.extend(
                [
                    f"### {run_id}",
                    "",
                    f"Reviewer: {reflection.reviewer_id or 'see review history'}",
                    "",
                    reflection.revised_frame,
                    "",
                    f"Unresolved difference: {reflection.disagreement}",
                    f"Next investigation: {reflection.next_research_question}",
                    f"Revisit when: {reflection.revision_trigger}",
                    "Evidence considered: " + ", ".join(reflection.evidence_refs),
                    "",
                    "This is an attributed framing decision, not a factual finding.",
                    "",
                ]
            )
    for title, exercises in SECTIONS.items():
        lines.extend([f"## {title}", ""])
        selected = [
            claim
            for claim in state.reportable_claims()
            if claim.exercise_id in exercises
        ]
        if not selected:
            lines.append("_No evidence-qualified claims yet._")
        for claim in selected:
            lines.extend(
                [
                    f"- **{claim.statement}**",
                    f"  - Claim: `{claim.claim_id}`",
                    f"  - Type: {claim.claim_type}; confidence: {claim.confidence}",
                    "  - Evidence: " + ", ".join(claim.evidence_refs),
                    "  - Validation evidence: "
                    + ", ".join(
                        state.validations[claim.claim_id].evidence_refs
                        if claim.claim_id in state.validations
                        else []
                    ),
                    f"  - Rationale: {claim.public_reasoning_summary}",
                    "  - Human evidence judgment: "
                    + (
                        state.validations[claim.claim_id].public_reasoning_summary
                        if claim.claim_id in state.validations
                        else "Not recorded."
                    ),
                ]
            )
        lines.append("")
    (output / "design_research_brief.md").write_text("\n".join(lines), encoding="utf-8")

    provenance = [
        "# Provenance report",
        "",
        f"Ledger SHA-256: `{digest}`",
        "",
        "## Sources",
        "",
    ]
    for source in state.evidence.values():
        provenance.extend(
            [
                f"### {source.source_id}",
                "",
                f"Path: `{source.source_path}`",
                "",
                f"SHA-256: `{source.content_sha256}`",
                "",
            ]
        )
    provenance.extend(["## Claims", ""])
    for claim_id, claim in state.claims.items():
        provenance.extend(
            [
                f"- `{claim_id}` — {claim.statement}",
                f"  - review: {state.reviews[claim_id]}",
                f"  - status: {state.statuses[claim_id]}",
                "  - evidence: " + ", ".join(claim.evidence_refs),
            ]
        )
    (output / "provenance_report.md").write_text(
        "\n".join(provenance) + "\n", encoding="utf-8"
    )
    return output
