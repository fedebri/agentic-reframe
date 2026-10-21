"""One explicitly budgeted API run with fictional inputs; never approves claims."""

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from agentic_dt.evals import evaluate_run
from agentic_dt.schemas import RunManifest
from agentic_dt.workflow import run_exercise

pytestmark = pytest.mark.live


def test_analyst_api_and_checkpoint_resume(live_budget: Decimal) -> None:
    root = Path(__file__).resolve().parents[2]
    output = root / "outputs" / "v2" / "live-tests" / f"smoke-{uuid4().hex}"
    print(f"Live test artifacts: {output}")
    configuration = yaml.safe_load((root / "config" / "project.yaml").read_text())
    configuration["paths"] = {
        "brief": str(root / "docs" / "examples" / "library_brief.md"),
        "outputs": str(output),
        "ledger": str(output / "ledger" / "events.jsonl"),
    }
    configuration["workflow"]["critic_policy"] = "disabled"
    for name in ("analyst_prompt", "critic_prompt"):
        configuration["workflow"][name] = str(root / configuration["workflow"][name])
    for exercise in configuration["exercises"]:
        exercise["source"] = str(root / exercise["source"])
    configuration["model"]["max_retries"] = 0
    config_path = output / "project" / "config" / "project.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=False)
    config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    human_frame = output / "human_frame.yaml"
    human_frame.write_text(
        yaml.safe_dump(
            {
                "author_id": "fictional-api-test-fixture",
                "exercise_id": "frame_challenge",
                "framing": "Investigate fictional newcomers' access to workshops.",
                "observations": ["The fictional brief supplies no attendance data."],
                "assumptions": ["Participant roles may face different barriers."],
                "alternative_frame": "Investigate timing before awareness.",
                "open_questions": ["Which account would distinguish these frames?"],
            }
        ),
        encoding="utf-8",
    )
    evidence = [root / "docs" / "examples" / "library_interview.md"]
    directory = run_exercise(
        config_path,
        "frame_challenge",
        output / "run",
        evidence,
        False,
        True,
        live_budget,
        human_frame_path=human_frame,
    )
    manifest_path = directory / "input_manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = RunManifest.model_validate_json(original_manifest)
    assert manifest.citation_format == "passage_ids"
    assert (directory / "analyst_draft.json").exists()
    log_path = directory / "run_events.jsonl"
    original_log = log_path.read_bytes()
    logs = [json.loads(line) for line in original_log.splitlines()]
    received = [event for event in logs if event["event_type"] == "response_received"]
    assert len(received) == 1
    assert received[0]["details"]["response_id"]
    assert received[0]["details"]["request_id"]
    assert received[0]["details"]["usage"]["input_tokens"] > 0
    assert received[0]["details"]["usage"]["output_tokens"] > 0
    assert not Path(manifest.ledger_path).exists()
    assert (
        json.loads((directory / "status.json").read_text())["state"]
        == "awaiting_review"
    )
    assert (directory / "comparison.md").exists()

    evaluation = json.loads(evaluate_run(directory, output / "eval.json").read_text())
    assert evaluation["source_reference_validity"] == 1
    assert evaluation["passage_accuracy"] == 1
    assert evaluation["deliverable_coverage"] == 1
    assert Decimal(evaluation["reserved_usd"]) <= live_budget

    # Reusing verified checkpoints must not call even the token-counting endpoint.
    run_exercise(
        config_path,
        "frame_challenge",
        directory,
        evidence,
        False,
        True,
        live_budget,
        human_frame_path=human_frame,
    )
    assert manifest_path.read_bytes() == original_manifest
    assert log_path.read_bytes() == original_log
    assert not Path(manifest.ledger_path).exists()
