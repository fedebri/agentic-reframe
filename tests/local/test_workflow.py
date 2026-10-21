import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agentic_dt import workflow as workflow_module
from agentic_dt.evals import evaluate_run
from agentic_dt.graph import replay
from agentic_dt.reports import compile_reports
from agentic_dt.review import apply_review, export_review
from agentic_dt.schemas import RunManifest
from agentic_dt.workflow import _critic_request, run_exercise, validate_project


def _analysis(manifest: RunManifest) -> dict:
    evidence = manifest.sources[0].source_id
    response = {
        "role": "analyst",
        "exercise_id": manifest.exercise_id,
        "claims": [
            {
                "local_id": "frame-1",
                "statement": "The challenge needs a testable audience boundary.",
                "claim_type": "hypothesis",
                "deliverable": "framed_challenge",
                "evidence_refs": [evidence],
                "citations": [
                    {
                        "source_id": evidence,
                        "start_line": 1,
                        "end_line": 1,
                        "quote": manifest.sources[0].content.splitlines()[0],
                    }
                ],
                "derived_from": [],
                "confidence": 0.4,
                "public_reasoning_summary": "The brief leaves the audience broad.",
                "open_questions": ["Who is directly affected?"],
            },
            {
                "local_id": "audience-1",
                "statement": "The named audience remains provisional.",
                "claim_type": "assumption",
                "deliverable": "audience",
                "evidence_refs": [evidence],
                "citations": [
                    {
                        "source_id": evidence,
                        "start_line": 1,
                        "end_line": 1,
                        "quote": manifest.sources[0].content.splitlines()[0],
                    }
                ],
                "derived_from": [],
                "confidence": 0.3,
                "public_reasoning_summary": "No field evidence is assigned.",
                "open_questions": ["Which roles should be distinguished?"],
            },
        ],
    }
    if manifest.citation_format == "passage_ids":
        for claim in response["claims"]:
            claim["citations"] = [{"source_id": evidence, "passage_id": "p1"}]
    return response


def test_preview_freezes_scope_and_keeps_untrusted_text_in_user_input(
    project: Path,
) -> None:
    validate_project(project)
    directory = run_exercise(
        project,
        "frame_challenge",
        project.parent.parent / "preview",
        [Path("evidence.md")],
        False,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    request = json.loads((directory / "analyst_request.json").read_text())
    assert manifest.sources[1].source_path.endswith("evidence.md")
    assert "UNTRUSTED BRIEF" not in request["instructions"]
    assert "UNTRUSTED BRIEF" in request["input"][0]["content"]
    assert "tools" not in request
    assert "HUMAN-INDEPENDENT-INTERPRETATION" not in json.dumps(request)
    assert "HUMAN-INDEPENDENT-INTERPRETATION" in manifest.human_frame.content
    assert manifest.citation_format == "passage_ids"
    sources = json.loads(request["input"][0]["content"])["sources"]
    assert "content" not in sources[0]
    assert sources[0]["passages"] == [
        {"passage_id": "p1", "text": manifest.sources[0].content}
    ]
    citation = request["text"]["format"]["schema"]["$defs"]["PassageReference"]
    assert set(citation["properties"]) == {"source_id", "passage_id"}
    assert json.loads((directory / "status.json").read_text())["state"] == "prepared"


def test_offline_run_review_eval_and_compile(
    project: Path, fake_client_type, tmp_path: Path
) -> None:
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
        Decimal("1.00"),
        client=client,
    )
    assert client.responses.calls == 1
    assert not Path(manifest.ledger_path).exists()
    assert json.loads((directory / "status.json").read_text())["state"] == (
        "awaiting_review"
    )

    review_path = export_review(directory, tmp_path / "review.yaml", "tester")
    review = yaml.safe_load(review_path.read_text())
    for decision in review["decisions"]:
        decision["decision"] = "accept"
        decision["validation_status"] = "supported"
        decision["public_reasoning_summary"] = "Checked against assigned evidence."
    review["reflection"] = {
        "revised_frame": "Understand which audience boundaries matter in practice.",
        "disagreement": "The analyst stresses audience labels; timing may also matter.",
        "assumptions_reconsidered": ["One audience label may hide different roles."],
        "next_research_question": "Which roles face different access barriers?",
        "revision_trigger": "A participant identifies a different barrier.",
        "evidence_refs": [manifest.sources[0].source_id],
    }
    review_path.write_text(yaml.safe_dump(review, sort_keys=False))
    receipt = apply_review(review_path)
    assert receipt.exists()
    assert apply_review(review_path) == receipt
    state = replay(Path(manifest.ledger_path))
    assert len(state.reportable_claims()) == 2
    selected_id = state.reportable_claims()[0].claim_id
    next_run = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "next-run",
        [],
        False,
        False,
        None,
        context_claim_ids=[selected_id],
        human_frame_path=Path("human_frame.yaml"),
    )
    next_manifest = RunManifest.model_validate_json(
        (next_run / "input_manifest.json").read_bytes()
    )
    assert [claim.claim_id for claim in next_manifest.approved_context] == [selected_id]

    eval_path = evaluate_run(directory, tmp_path / "eval.json")
    evaluation = json.loads(eval_path.read_text())
    assert evaluation["source_reference_validity"] == 1
    assert evaluation["passage_accuracy"] == 1
    assert evaluation["independent_frame_recorded"]
    assert evaluation["deliverable_coverage"] == 1
    reports = compile_reports(Path(manifest.ledger_path), tmp_path / "reports")
    assert "testable audience" in (reports / "design_research_brief.md").read_text()


def test_optional_critic_has_distinct_non_claim_contract(
    project: Path, fake_client_type, tmp_path: Path
) -> None:
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "critic-run",
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
        "next_action": "request_evidence",
        "next_question": "Which participant observation would distinguish the frames?",
        "issues": [
            {
                "claim_id": "frame-1",
                "severity": "warning",
                "category": "evidence",
                "message": "The claim relies only on the brief.",
                "evidence_refs": [manifest.sources[0].source_id],
            }
        ],
    }
    client = fake_client_type([_analysis(manifest), critique])
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        True,
        True,
        Decimal("1.00"),
        client=client,
    )
    saved = json.loads((directory / "critic_response.json").read_text())
    assert saved["recommendation"] == "review_carefully"
    assert "claims" not in saved
    assert saved["next_action"] == "request_evidence"
    critic_request = json.loads((directory / "critic_request.json").read_text())
    assert "HUMAN-INDEPENDENT-INTERPRETATION" not in json.dumps(critic_request)
    critic_input = json.loads(critic_request["input"][0]["content"])
    assert "content" not in critic_input["sources"][0]
    assert critic_input["sources"][0]["passages"][0]["passage_id"] == "p1"
    logs = [
        json.loads(line)
        for line in (directory / "run_events.jsonl").read_text().splitlines()
    ]
    assert any(event["event_type"] == "evidence_requested" for event in logs)
    assert client.responses.calls == 2


def test_large_critic_request_resumes_without_repeating_analyst(
    project, fake_client_type, tmp_path, monkeypatch
):
    (project.parent.parent / "docs/brief.md").write_text(
        "FICTIONAL long passage: " + "observation " * 1000,
        encoding="utf-8",
    )
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "large-critic",
        [],
        True,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest_path = directory / "input_manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = RunManifest.model_validate_json(original_manifest)
    analyst = fake_client_type([_analysis(manifest)])
    # Reproduce the old failure after the analyst checkpoint, before any critic
    # request can be saved or sent. Only the fixture service is used.
    with monkeypatch.context() as patch:
        patch.setattr(
            workflow_module,
            "_critic_request",
            lambda manifest, response, **_kwargs: _critic_request(
                manifest, response, compact_citations=False
            ),
        )
        with pytest.raises(ValueError, match="Critic request exceeds"):
            run_exercise(
                project,
                "frame_challenge",
                directory,
                [],
                True,
                True,
                Decimal("1"),
                client=analyst,
            )
    original_analysis = (directory / "analyst_response.json").read_bytes()
    assert analyst.responses.calls == 1
    assert not (directory / "critic_request.json").exists()
    critic = fake_client_type(
        [
            {
                "role": "critic",
                "exercise_id": "frame_challenge",
                "recommendation": "proceed",
                "issues": [],
                "next_action": "review",
                "next_question": None,
            }
        ]
    )
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        True,
        True,
        Decimal("1"),
        client=critic,
    )
    assert critic.responses.calls == 1
    assert manifest_path.read_bytes() == original_manifest
    assert (directory / "analyst_response.json").read_bytes() == original_analysis
    request = json.loads((directory / "critic_request.json").read_text())
    assert len(json.dumps(request).encode()) <= manifest.model.max_input_bytes
    payload = json.loads(request["input"][0]["content"])
    assert payload["citation_format"] == "passage_ids"
    for claim in payload["analyst_response"]["claims"]:
        assert claim["citations"] == [
            {
                "source_id": manifest.sources[0].source_id,
                "passage_id": "p1",
            }
        ]
    assert (
        payload["sources"][0]["passages"][0]["text"]
        == manifest.sources[0].content.strip()
    )
    assert not Path(manifest.ledger_path).exists()


def test_saved_legacy_critic_request_is_preserved_on_retry(
    project, fake_client_type, tmp_path, monkeypatch
):
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "legacy-critic",
        [],
        True,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            workflow_module,
            "_critic_request",
            lambda manifest, response, **_kwargs: _critic_request(
                manifest, response, compact_citations=False
            ),
        )
        with pytest.raises(StopIteration):
            run_exercise(
                project,
                "frame_challenge",
                directory,
                [],
                True,
                True,
                Decimal("1"),
                client=fake_client_type([_analysis(manifest)]),
            )
    saved_request = (directory / "critic_request.json").read_bytes()
    payload = json.loads(json.loads(saved_request)["input"][0]["content"])
    assert "citation_format" not in payload
    assert "quote" in payload["analyst_response"]["claims"][0]["citations"][0]
    critic = fake_client_type(
        [
            {
                "role": "critic",
                "exercise_id": "frame_challenge",
                "recommendation": "proceed",
                "issues": [],
                "next_action": "review",
                "next_question": None,
            }
        ]
    )
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        True,
        True,
        Decimal("1"),
        retry_failed=True,
        client=critic,
    )
    assert critic.responses.calls == 1
    assert (directory / "critic_request.json").read_bytes() == saved_request


def test_budget_blocks_call_before_generation(
    project: Path, fake_client_type, tmp_path: Path
) -> None:
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "budget-run",
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
    with pytest.raises(ValueError, match="Maximum estimated cost"):
        run_exercise(
            project,
            "frame_challenge",
            directory,
            [],
            False,
            True,
            Decimal("0.000001"),
            client=client,
        )
    assert client.responses.calls == 0
