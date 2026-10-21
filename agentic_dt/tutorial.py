"""A zero-cost fictional rehearsal using the real version 2 workflow."""

import json
from decimal import Decimal
from pathlib import Path

import yaml

from .evals import evaluate_run
from .reports import compile_reports
from .review import apply_review, export_review
from .schemas import RunManifest
from .sources import index_passages
from .workflow import run_exercise


class _Count:
    input_tokens = 100


class _InputTokens:
    def count(self, **_request):
        return _Count()


class _Usage:
    input_tokens = 100
    output_tokens = 200

    def model_dump(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


class _Response:
    def __init__(self, index: int, text: str):
        self.id = f"tutorial-response-{index}"
        self._request_id = f"tutorial-request-{index}"
        self.model = "fictional-tutorial-model"
        self.status = "completed"
        self.usage = _Usage()
        self.output = []
        self.output_text = text


class _Responses:
    def __init__(self, outputs: list[str]):
        self.input_tokens = _InputTokens()
        self._outputs = iter(outputs)
        self._index = 0

    def create(self, **_request):
        self._index += 1
        return _Response(self._index, next(self._outputs))


class _TutorialClient:
    def __init__(self, outputs: list[str]):
        self.responses = _Responses(outputs)


def run_tutorial(config_path: Path, output: Path) -> Path:
    """Rehearse independent framing, a question, new evidence, and a correction."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = config_path.resolve().parent.parent
    configuration = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    brief_path = output / "brief.md"
    brief_path.write_text(
        "FICTIONAL: A library wants to understand low evening workshop attendance.\n"
        "The sponsor assumes residents do not hear about sessions.\n",
        encoding="utf-8",
    )
    notes_path = output / "participant_notes.md"
    notes_path.write_text(
        "FICTIONAL interview with participant R1, for software rehearsal.\n"
        "I saw the notice. My shift ends at 18:00, after the 17:30 session starts.\n",
        encoding="utf-8",
    )
    configuration["paths"] = {
        "brief": str(brief_path),
        "outputs": str(output / "runs"),
        "ledger": str(output / "ledger" / "events.jsonl"),
    }
    for key in ("analyst_prompt", "critic_prompt"):
        configuration["workflow"][key] = str(root / configuration["workflow"][key])
    configuration["workflow"]["critic_policy"] = "requested"
    for exercise in configuration["exercises"]:
        exercise["source"] = str(root / exercise["source"])
    tutorial_config = output / "project" / "config" / "project.yaml"
    tutorial_config.parent.mkdir(parents=True)
    tutorial_config.write_text(yaml.safe_dump(configuration), encoding="utf-8")

    summaries = []
    for iteration in (1, 2):
        independent_path = output / f"human_frame_{iteration}.yaml"
        framing = (
            "How might we understand why residents do not hear about workshops?"
            if iteration == 1
            else "How might we understand access for residents aware of workshops?"
        )
        independent_path.write_text(
            yaml.safe_dump(
                {
                    "author_id": "fictional-researcher",
                    "exercise_id": "frame_challenge",
                    "framing": framing,
                    "observations": [
                        "The sponsor reports low attendance."
                        if iteration == 1
                        else notes_path.read_text().splitlines()[1]
                    ],
                    "assumptions": [
                        "Awareness is the main barrier."
                        if iteration == 1
                        else "Work schedules may affect access for other residents."
                    ],
                    "alternative_frame": (
                        "Timing may block residents who know about sessions."
                        if iteration == 1
                        else "Care responsibilities may be another barrier."
                    ),
                    "open_questions": [
                        "Which observation would distinguish awareness from access?"
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        directory = output / ("run" if iteration == 1 else "follow_up_run")
        evidence_paths = [] if iteration == 1 else [notes_path]
        run_exercise(
            tutorial_config,
            "frame_challenge",
            directory,
            evidence_paths,
            True,
            False,
            None,
            human_frame_path=independent_path,
        )
        manifest = RunManifest.model_validate_json(
            (directory / "input_manifest.json").read_bytes()
        )
        source = manifest.sources[-1] if iteration == 2 else manifest.sources[0]
        passage_id = next(iter(index_passages(source)))
        statements = (
            [
                "Lack of awareness is the sole barrier to attendance.",
                "An awareness-only frame could hide access constraints.",
                "The brief does not establish which residents miss sessions.",
            ]
            if iteration == 1
            else [
                "Investigate access barriers among residents who know about sessions.",
                "R1 reports awareness but finishes work after the workshop starts.",
                "One participant account cannot establish barriers for all residents.",
            ]
        )
        claims = [
            {
                "local_id": f"tutorial-{index}",
                "statement": statement,
                "claim_type": "observation"
                if iteration == 2 and index == 2
                else "hypothesis",
                "deliverable": deliverable,
                "evidence_refs": [source.source_id],
                "citations": [
                    {
                        "source_id": source.source_id,
                        "passage_id": passage_id,
                    }
                ],
                "derived_from": [],
                "confidence": 0.4,
                "public_reasoning_summary": (
                    "FICTIONAL proposal: the sponsor's assumption needs testing."
                    if iteration == 1
                    else "FICTIONAL: R1 challenges the awareness-only assumption."
                ),
                "open_questions": ["Who experiences a different barrier?"],
            }
            for index, (deliverable, statement) in enumerate(
                zip(manifest.deliverables, statements, strict=True), start=1
            )
        ]
        analysis = json.dumps(
            {
                "role": "analyst",
                "exercise_id": manifest.exercise_id,
                "claims": claims,
            }
        )
        critique = json.dumps(
            {
                "role": "critic",
                "exercise_id": manifest.exercise_id,
                "recommendation": "review_carefully",
                "issues": [
                    {
                        "claim_id": "tutorial-1",
                        "severity": "warning",
                        "category": "evidence",
                        "message": (
                            "The sponsor's assumption does not establish causality."
                            if iteration == 1
                            else "One account cannot establish all residents' barriers."
                        ),
                        "evidence_refs": [source.source_id],
                    }
                ],
                "next_action": "request_evidence",
                "next_question": (
                    "Do residents miss notices, or know but cannot attend?"
                    if iteration == 1
                    else "Do other participant roles report the same timing barrier?"
                ),
            }
        )
        run_exercise(
            tutorial_config,
            "frame_challenge",
            directory,
            evidence_paths,
            True,
            True,
            Decimal("1.00"),
            client=_TutorialClient([analysis, critique]),
        )
        review_path = export_review(
            directory, output / f"review_{iteration}.yaml", "fictional-researcher"
        )
        worksheet = yaml.safe_load(review_path.read_text(encoding="utf-8"))
        for decision in worksheet["decisions"]:
            decision["decision"] = "accept"
            decision["public_reasoning_summary"] = (
                "FICTIONAL: retain for inquiry; this is not validated field research."
            )
            if iteration == 2 and decision["local_id"] == "tutorial-2":
                decision["validation_status"] = "supported"
                decision["public_reasoning_summary"] = (
                    "FICTIONAL: an exact restatement of the attributed R1 fixture."
                )
            if iteration == 2 and decision["local_id"] == "tutorial-1":
                decision["revised_statement"] = framing
                decision["revision_confidence"] = 0.4
        worksheet["reflection"] = {
            "revised_frame": framing
            if iteration == 2
            else ("Understand awareness and access barriers before choosing a frame."),
            "disagreement": (
                "The first analyst hypothesis overstates what the sponsor knows."
                if iteration == 1
                else "A single account supports a question, not a population claim."
            ),
            "assumptions_reconsidered": ["Awareness is the only attendance barrier."],
            "next_research_question": json.loads(critique)["next_question"],
            "revision_trigger": "A participant account exposes a different constraint.",
            "evidence_refs": [source.source_id],
        }
        review_path.write_text(
            yaml.safe_dump(worksheet, sort_keys=False), encoding="utf-8"
        )
        apply_review(review_path)
        evaluate_run(directory, output / f"eval_{iteration}.json")
        summaries.append(
            {
                "run_id": manifest.run_id,
                "directory": str(directory),
                "frame": framing,
                "source_id": source.source_id,
            }
        )

    # Correct the first run using the later observation, preserving its full history.
    correction_path = export_review(
        output / "run", output / "correction.yaml", "fictional-researcher", [notes_path]
    )
    correction = yaml.safe_load(correction_path.read_text(encoding="utf-8"))
    for decision in correction["decisions"]:
        decision["decision"] = "accept"
        decision["public_reasoning_summary"] = (
            "FICTIONAL: retain this provisional question."
        )
    observation_id = f"{summaries[1]['run_id']}:tutorial-2"
    original_id = f"{summaries[0]['run_id']}:tutorial-1"
    correction["decisions"][0].update(
        decision="reject",
        validation_status="deprecated",
        public_reasoning_summary="FICTIONAL: R1 refutes the sole-barrier assumption.",
        citations=[
            {
                "source_id": summaries[1]["source_id"],
                "start_line": 2,
                "end_line": 2,
                "quote": notes_path.read_text().splitlines()[1],
            }
        ],
    )
    correction["relations"] = [
        {
            "source_id": observation_id,
            "target_id": original_id,
            "relation": "invalidates",
            "public_reasoning_summary": (
                "R1 knows about sessions but cannot attend their start time."
            ),
        }
    ]
    correction["reflection"] = {
        "revised_frame": summaries[1]["frame"],
        "disagreement": "The awareness-only assumption failed its counterexample test.",
        "assumptions_reconsidered": ["Awareness is the sole attendance barrier."],
        "next_research_question": "Which barriers affect other participant roles?",
        "revision_trigger": "Varied participant accounts change the frame's scope.",
        "evidence_refs": [summaries[1]["source_id"]],
    }
    correction_path.write_text(
        yaml.safe_dump(correction, sort_keys=False), encoding="utf-8"
    )
    apply_review(correction_path)
    evaluate_run(output / "follow_up_run", output / "eval_report.json")
    compile_reports(output / "ledger" / "events.jsonl", output / "reports")
    (output / "tutorial_summary.json").write_text(
        json.dumps(
            {
                "fictional": True,
                "actual_api_cost_usd": "0",
                "runs": summaries,
                "deprecated_claim": original_id,
                "new_observation": observation_id,
                "claim_of_improved_human_reasoning": None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "TUTORIAL.md").write_text(
        "# Fictional inquiry cycle\n\n"
        "No API call, real fieldwork, or real human assessment occurred.\n\n"
        "1. Read human_frame_1.yaml before run/comparison.md.\n"
        "2. Inspect the critic's question and review_1.yaml reflection.\n"
        "3. Read participant_notes.md and human_frame_2.yaml.\n"
        "4. Compare follow_up_run/comparison.md with the original interpretation.\n"
        "5. Inspect correction.yaml: the old assumption is retained but deprecated.\n"
        "6. Read reports/design_research_brief.md and eval_report.json.\n\n"
        "Structural scores establish source and passage checks only. Human reasoning "
        "benefits require an independent assessor and follow-up without AI.\n",
        encoding="utf-8",
    )
    return output
