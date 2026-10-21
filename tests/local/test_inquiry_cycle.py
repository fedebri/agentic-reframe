"""Regression cases for independent reasoning, correction, and interrupted commits."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from test_workflow import _analysis

from agentic_dt import review as review_module
from agentic_dt.evals import evaluate_run
from agentic_dt.graph import replay
from agentic_dt.review import apply_review, export_review
from agentic_dt.schemas import RunManifest
from agentic_dt.workflow import run_exercise


def decide_review(path: Path) -> dict:
    """Fill a fictional review while retaining editable decisions for each case."""
    data = yaml.safe_load(path.read_text())
    directory = Path(data["run_directory"])
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    for decision in data["decisions"]:
        decision.update(
            decision="accept",
            validation_status="supported",
            public_reasoning_summary=(
                "Fixture judgment checked against the assigned passage."
            ),
        )
    data["reflection"] = {
        "revised_frame": (
            "Investigate the different barriers affecting participant roles."
        ),
        "disagreement": "The analyst's audience labels may conceal timing differences.",
        "assumptions_reconsidered": ["The audience has one shared barrier."],
        "next_research_question": "Which roles experience different barriers?",
        "revision_trigger": "A participant account contradicts this framing.",
        "evidence_refs": [manifest.sources[0].source_id],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return data


@pytest.fixture
def completed(project, tmp_path, fake_client_type):
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "run",
        [],
        False,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    client = fake_client_type([_analysis(manifest)])
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        False,
        True,
        Decimal("1"),
        client=client,
    )
    return project, directory, manifest


@pytest.fixture
def worksheet(completed, tmp_path):
    _, directory, _ = completed
    path = export_review(directory, tmp_path / "review.yaml", "researcher")
    decide_review(path)
    return path


def test_independent_frame_is_required_before_preparation(project, tmp_path):
    with pytest.raises(ValueError, match="independent interpretation"):
        run_exercise(
            project,
            "frame_challenge",
            tmp_path / "without-frame",
            [],
            False,
            False,
            None,
        )
    assert not (tmp_path / "without-frame").exists()


def test_resume_recovers_after_the_response_checkpoint(
    completed, tmp_path, fake_client_type
):
    project, directory, manifest = completed
    status_path = directory / "status.json"
    status_path.write_text(json.dumps({"state": "running", "run_id": manifest.run_id}))
    client = fake_client_type([])
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        False,
        True,
        Decimal("1"),
        client=client,
    )
    assert client.responses.calls == 0
    assert json.loads(status_path.read_text())["state"] == "awaiting_review"
    assert export_review(directory, tmp_path / "recovered.yaml", "researcher").exists()


def test_changed_committed_review_is_rejected(worksheet, completed):
    _, _, manifest = completed
    apply_review(worksheet)
    before = Path(manifest.ledger_path).read_bytes()
    data = yaml.safe_load(worksheet.read_text())
    data["decisions"][0]["decision"] = "reject"
    worksheet.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="Applied review changed"):
        apply_review(worksheet)
    assert Path(manifest.ledger_path).read_bytes() == before


def test_commit_rebuilds_a_missing_receipt(worksheet, completed, monkeypatch):
    _, _, manifest = completed
    original_replace = Path.replace

    def interrupt_receipt(path, target):
        if str(target).endswith(".receipt.json"):
            raise OSError("simulated interruption after ledger commit")
        return original_replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupt_receipt)
        with pytest.raises(OSError, match="simulated interruption"):
            apply_review(worksheet)
    before = Path(manifest.ledger_path).read_bytes()
    assert apply_review(worksheet).exists()
    assert Path(manifest.ledger_path).read_bytes() == before


def test_commit_resumes_a_complete_line_prefix(worksheet, completed, monkeypatch):
    _, _, manifest = completed
    append = review_module.append_events

    def interrupt_append(path, events):
        append(path, events[:3])
        raise OSError("simulated interruption during batch append")

    with monkeypatch.context() as patch:
        patch.setattr(review_module, "append_events", interrupt_append)
        with pytest.raises(OSError, match="simulated interruption"):
            apply_review(worksheet)
    prefix = Path(manifest.ledger_path).read_bytes()
    apply_review(worksheet)
    assert Path(manifest.ledger_path).read_bytes().startswith(prefix)
    state = replay(Path(manifest.ledger_path))
    assert manifest.run_id in state.completed_runs
    assert len(state.reportable_claims()) == 2


def test_correction_retains_history_and_blocks_dependent_claims(
    worksheet, completed, tmp_path, fake_client_type
):
    project, directory, first = completed
    apply_review(worksheet)
    prior_id = f"{first.run_id}:frame-1"
    second_directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "dependent",
        [],
        False,
        False,
        None,
        context_claim_ids=[prior_id],
        human_frame_path=Path("human_frame.yaml"),
    )
    second = RunManifest.model_validate_json(
        (second_directory / "input_manifest.json").read_bytes()
    )
    response = _analysis(second)
    for claim in response["claims"]:
        claim["derived_from"] = [prior_id]
    run_exercise(
        project,
        "frame_challenge",
        second_directory,
        [],
        False,
        True,
        Decimal("1"),
        context_claim_ids=[prior_id],
        client=fake_client_type([response]),
    )
    second_review = export_review(
        second_directory, tmp_path / "dependent.yaml", "person"
    )
    second_data = decide_review(second_review)
    second_data["decisions"][0].update(
        revised_statement="Investigate access barriers before narrowing the audience.",
        revision_confidence=0.5,
    )
    second_review.write_text(yaml.safe_dump(second_data))
    apply_review(second_review)
    ledger_path = Path(first.ledger_path)
    previous = ledger_path.read_bytes()
    correction = export_review(directory, tmp_path / "correction.yaml", "person")
    data = decide_review(correction)
    data["decisions"][0]["validation_status"] = "contested"
    correction.write_text(yaml.safe_dump(data))
    apply_review(correction)
    state = replay(ledger_path)
    dependent_ids = {f"{second.run_id}:frame-1", f"{second.run_id}:audience-1"}
    human_revision = next(
        claim for claim in state.claims.values() if claim.agent_id == "human"
    )
    dependent_ids.add(human_revision.claim_id)
    assert any(
        edge.source_id == human_revision.claim_id
        and edge.target_id == prior_id
        and edge.relation == "depends_on"
        for edge in state.edges.values()
    )
    assert dependent_ids <= state.blocked_claim_ids()
    assert not dependent_ids & {claim.claim_id for claim in state.context_claims()}
    assert not dependent_ids & {claim.claim_id for claim in state.reportable_claims()}
    assert ledger_path.read_bytes().startswith(previous)
    assert state.statuses[prior_id] == "contested"


def test_human_can_author_a_revision(worksheet, completed, tmp_path):
    _, directory, manifest = completed
    apply_review(worksheet)
    correction = export_review(directory, tmp_path / "authored.yaml", "human-author")
    data = decide_review(correction)
    data["decisions"][0]["revised_statement"] = (
        "Investigate timing before narrowing the audience."
    )
    data["decisions"][0]["validation_status"] = "proposed"
    data["decisions"][0]["revision_confidence"] = 0.6
    correction.write_text(yaml.safe_dump(data))
    apply_review(correction)
    state = replay(Path(manifest.ledger_path))
    revised = [claim for claim in state.claims.values() if claim.agent_id == "human"]
    assert len(revised) == 1
    assert revised[0].author_id == "human-author"
    assert revised[0].confidence == 0.6
    assert state.reviews[f"{manifest.run_id}:frame-1"] == "rejected"
    assert state.statuses[revised[0].claim_id] == "proposed"
    assert state.reflections[manifest.run_id].next_research_question
    assert state.reflections[manifest.run_id].reviewer_id == "human-author"


def test_human_revision_requires_its_own_confidence(worksheet):
    data = yaml.safe_load(worksheet.read_text())
    data["decisions"][0]["revised_statement"] = "Investigate access barriers."
    worksheet.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="revision_confidence"):
        apply_review(worksheet)


def test_new_passages_persist_when_the_status_is_reaffirmed(
    worksheet, completed, tmp_path
):
    project, directory, manifest = completed
    apply_review(worksheet)
    evidence = tmp_path / "new-account.md"
    evidence.write_text(
        "FICTIONAL R1: I know about sessions but cannot arrive on time.\n"
    )
    correction = export_review(
        directory, tmp_path / "new-evidence.yaml", "researcher", [evidence]
    )
    data = decide_review(correction)
    source = data["additional_sources"][0]
    assert source["source_id"] in correction.with_suffix(".md").read_text()
    data["decisions"][0]["citations"] = [
        {
            "source_id": source["source_id"],
            "start_line": 1,
            "end_line": 1,
            "quote": source["content"].strip(),
        }
    ]
    correction.write_text(yaml.safe_dump(data))
    apply_review(correction)
    state = replay(Path(manifest.ledger_path))
    claim_id = f"{manifest.run_id}:frame-1"
    assert state.statuses[claim_id] == "supported"
    assert state.validations[claim_id].citations[0].source_id == source["source_id"]
    next_run = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "auditable-context",
        [],
        False,
        False,
        None,
        context_claim_ids=[claim_id],
        human_frame_path=Path("human_frame.yaml"),
    )
    next_manifest = RunManifest.model_validate_json(
        (next_run / "input_manifest.json").read_bytes()
    )
    assert source["source_id"] in {item.source_id for item in next_manifest.sources}


def test_stale_review_cannot_append_over_a_later_commit(completed, worksheet, tmp_path):
    _, directory, manifest = completed
    other = export_review(directory, tmp_path / "concurrent.yaml", "other-person")
    decide_review(other)
    apply_review(worksheet)
    before = Path(manifest.ledger_path).read_bytes()
    with pytest.raises(ValueError, match="Ledger changed"):
        apply_review(other)
    assert Path(manifest.ledger_path).read_bytes() == before


def test_cyclic_required_premises_are_rejected_before_commit(
    completed, worksheet, tmp_path
):
    _, directory, manifest = completed
    apply_review(worksheet)
    correction = export_review(directory, tmp_path / "cycle.yaml", "researcher")
    data = decide_review(correction)
    first = f"{manifest.run_id}:frame-1"
    second = f"{manifest.run_id}:audience-1"
    data["relations"] = [
        {
            "source_id": source,
            "target_id": target,
            "relation": "depends_on",
            "public_reasoning_summary": "Fixture circular premise.",
        }
        for source, target in [(first, second), (second, first)]
    ]
    correction.write_text(yaml.safe_dump(data))
    before = Path(manifest.ledger_path).read_bytes()
    with pytest.raises(ValueError, match="cycle"):
        apply_review(correction)
    assert Path(manifest.ledger_path).read_bytes() == before


def test_critic_evidence_request_requires_a_question(
    project, tmp_path, fake_client_type
):
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "critic-without-question",
        [],
        True,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    critique = {
        "role": "critic",
        "exercise_id": manifest.exercise_id,
        "recommendation": "review_carefully",
        "issues": [],
        "next_action": "request_evidence",
        "next_question": None,
    }
    client = fake_client_type([_analysis(manifest), critique])
    with pytest.raises(ValueError, match="question"):
        run_exercise(
            project,
            "frame_challenge",
            directory,
            [],
            True,
            True,
            Decimal("1"),
            client=client,
        )
    assert client.responses.calls == 2
    assert not (directory / "critic_response.json").exists()


def test_human_reflection_is_a_required_decision(worksheet):
    data = yaml.safe_load(worksheet.read_text())
    data["reflection"] = None
    worksheet.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="comparison and research decision"):
        apply_review(worksheet)


def test_reviewer_requires_a_rationale_for_evidence_validation(worksheet):
    data = yaml.safe_load(worksheet.read_text())
    data["decisions"][0]["public_reasoning_summary"] = ""
    worksheet.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="passages and a rationale"):
        apply_review(worksheet)


@pytest.mark.parametrize(
    "reference",
    [
        {"source_id": None, "passage_id": "p999"},
        {"source_id": None, "passage_id": "p2"},
        {"source_id": "unassigned-source", "passage_id": "p1"},
    ],
)
def test_invalid_passage_is_rejected_before_saving_response(
    project, tmp_path, fake_client_type, reference
):
    (project.parent.parent / "evidence.md").write_text(
        "Participant note.\n\nAnother participant note.\n"
    )
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "bad-passage",
        [Path("evidence.md")],
        False,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    response = _analysis(manifest)
    reference = {
        **reference,
        "source_id": reference["source_id"] or manifest.sources[0].source_id,
    }
    response["claims"][0]["citations"] = [reference]
    client = fake_client_type([response])
    with pytest.raises(ValueError, match="unknown passage"):
        run_exercise(
            project,
            "frame_challenge",
            directory,
            [Path("evidence.md")],
            False,
            True,
            Decimal("1"),
            client=client,
        )
    assert not (directory / "analyst_response.json").exists()
    draft = json.loads((directory / "analyst_draft.json").read_text())
    assert draft["claims"][0]["citations"] == [reference]
    assert not Path(manifest.ledger_path).exists()
    with pytest.raises(ValueError, match="unfinished attempt"):
        run_exercise(
            project,
            "frame_challenge",
            directory,
            [Path("evidence.md")],
            False,
            True,
            Decimal("1"),
            client=client,
        )
    assert client.responses.calls == 1


def test_reasoning_assessment_is_separate_from_mechanical_scores(
    completed, worksheet, tmp_path
):
    _, directory, manifest = completed
    apply_review(worksheet)
    assessment = tmp_path / "assessment.yaml"
    assessment.write_text(
        yaml.safe_dump(
            {
                "run_id": manifest.run_id,
                "assessor_id": "independent-person",
                "condition": "independent_comparison",
                "evidence_grounding": 2,
                "assumption_critique": 3,
                "contextual_explanation": 2,
                "investigation_value": 4,
                "rationale": "Fixture ratings, not measured efficacy.",
                "unassisted_follow_up": "Explain a countercase without AI output.",
            }
        )
    )
    report_path = evaluate_run(directory, tmp_path / "rated.json", assessment)
    report = json.loads(report_path.read_text())
    assert report["source_reference_validity"] == 1
    assert report["passage_accuracy"] == 1
    assert report["reasoning_assessment"]["evidence_grounding"] == 2
    assert report["human_rubric"]["evidence_grounding_1_to_5"] is None
    assert report["reflection"]["assumptions_reconsidered"]
    assert report["model_calls"] == 1


def test_changed_response_cannot_be_exported_as_a_new_review(completed, tmp_path):
    _, directory, _ = completed
    response_path = directory / "analyst_response.json"
    response = json.loads(response_path.read_text())
    response["claims"][0]["statement"] = "An accidentally edited claim."
    response_path.write_text(json.dumps(response))
    with pytest.raises(ValueError, match="checkpoint"):
        export_review(directory, tmp_path / "changed.yaml", "person")
