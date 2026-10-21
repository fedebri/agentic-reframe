"""Comparison artifacts shared by run completion and human review export."""

from pathlib import Path

import yaml

from .schemas import (
    AnalystResponse,
    CriticResponse,
    FrozenSource,
    HumanFrame,
    RunManifest,
)


def write_comparison(
    manifest: RunManifest,
    analysis: AnalystResponse,
    critique: CriticResponse | None,
    output: Path,
    additional_sources: list[FrozenSource] | None = None,
) -> None:
    """Present independent interpretations, exact passages, and a research question."""
    frame = (
        HumanFrame.model_validate(yaml.safe_load(manifest.human_frame.content))
        if manifest.human_frame is not None
        else None
    )
    lines = ["# Inquiry comparison", "", f"Run: `{manifest.run_id}`", ""]
    if frame is not None:
        lines.extend(
            [
                "## Independent human interpretation",
                "",
                f"Author: {frame.author_id}",
                f"Snapshot SHA-256: `{manifest.human_frame.content_sha256}`",
                "",
                frame.framing,
                "",
                f"Alternative: {frame.alternative_frame}",
                "",
                "Assumptions:",
                "",
                *[f"- {item}" for item in frame.assumptions],
                "",
                "Observations:",
                "",
                *[f"- {item}" for item in frame.observations],
                "",
                "Questions:",
                "",
                *[f"- {item}" for item in frame.open_questions],
                "",
            ]
        )
    else:
        lines.extend(["No independent human frame was recorded for this run.", ""])
    lines.extend(["## Analyst interpretation and evidence", ""])
    sources = {source.source_id: source for source in manifest.sources}
    for claim in analysis.claims:
        lines.extend(
            [
                f"### {claim.local_id}: {claim.deliverable}",
                "",
                claim.statement,
                "",
                f"Type: {claim.claim_type}; proposed confidence: {claim.confidence}",
                f"Rationale: {claim.public_reasoning_summary}",
                "",
            ]
        )
        for citation in claim.citations:
            source = sources[citation.source_id]
            lines.extend(
                [
                    f"Source: `{citation.source_id}` — `{source.source_path}` "
                    f"lines {citation.start_line}–{citation.end_line}",
                    "",
                    *[f"> {line}" for line in citation.quote.splitlines()],
                    "",
                ]
            )
        if not claim.citations:
            lines.extend(["No exact passage citation (legacy proposal).", ""])
        lines.extend([f"- Open question: {item}" for item in claim.open_questions])
        lines.append("")
    if critique is not None:
        lines.extend(["## Critic findings", "", critique.recommendation, ""])
        lines.extend(
            f"- {issue.severity}: {issue.claim_id or 'whole draft'} — {issue.message}"
            for issue in critique.issues
        )
    if additional_sources:
        lines.extend(
            [
                "## New evidence for this review",
                "",
                "These sources were not in the original model context.",
                "",
            ]
        )
        for source in additional_sources:
            lines.extend(
                [
                    f"### {source.source_id}",
                    "",
                    f"Path: `{source.source_path}`",
                    f"SHA-256: `{source.content_sha256}`",
                    "",
                    *[
                        f"> {number}: {line}"
                        for number, line in enumerate(source.content.splitlines(), 1)
                    ],
                    "",
                ]
            )
    if critique is not None:
        lines.extend(
            [
                "",
                "## Suggested next step",
                "",
                f"Action: {critique.next_action}",
                critique.next_question
                or "Review the proposed claims against the evidence.",
                "",
            ]
        )
    lines.extend(
        [
            "## Researcher's judgment",
            "",
            "Record the disagreement, assumptions reconsidered, revised frame, next "
            "research question, and evidence that would change your judgment in "
            "the review worksheet. New field evidence requires a new run or a "
            "correction review; it never changes these frozen interpretations.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
