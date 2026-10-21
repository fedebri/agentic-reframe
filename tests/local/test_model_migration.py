"""Model settings survive checkpoint resume and the real SDK transport boundary."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from openai import OpenAI
from pydantic import ValidationError
from test_workflow import _analysis

from agentic_dt.config import load_config
from agentic_dt.schemas import RunManifest
from agentic_dt.workflow import run_exercise


def test_new_model_and_reasoning_use_the_real_sdk_offline(project, tmp_path):
    config = yaml.safe_load(project.read_text())
    config["model"].update(name="gpt-6-luna", reasoning_effort="none")
    project.write_text(yaml.safe_dump(config))
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "sdk",
        [],
        True,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest_path = directory / "input_manifest.json"
    original = manifest_path.read_bytes()
    manifest = RunManifest.model_validate_json(original)
    config["model"].update(name="different-later-model", reasoning_effort="high")
    project.write_text(yaml.safe_dump(config))
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        data = (
            _analysis(manifest)
            if payload["text"]["format"]["name"] == "design_research_analysis"
            else {
                "role": "critic",
                "exercise_id": "frame_challenge",
                "recommendation": "proceed",
                "issues": [],
                "next_action": "review",
                "next_question": None,
            }
        )
        return httpx.Response(
            200,
            headers={"x-request-id": "offline-sdk-request"},
            json={
                "id": f"resp-{len(requests)}",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "id": "msg-fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(data),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 100,
                    "total_tokens": 200,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    with OpenAI(
        api_key="fictional-key-no-api-call",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
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
    assert len(requests) == 4
    for path, payload in requests:
        assert payload["model"] == "gpt-6-luna"
        assert payload["reasoning"] == {"effort": "none"}
        if not path.endswith("/input_tokens"):
            assert payload["store"] is False
    assert manifest_path.read_bytes() == original
    assert not Path(manifest.ledger_path).exists()


def test_legacy_manifest_keeps_its_model_and_omits_reasoning(
    project, tmp_path, fake_client_type
):
    prepared = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "seed",
        [],
        False,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    data = json.loads((prepared / "input_manifest.json").read_text())
    data.pop("citation_format")
    data["model"].pop("reasoning_effort")
    data["model"]["name"] = "gpt-4.1-mini-2025-04-14"
    manifest = RunManifest.model_validate(data)
    directory = tmp_path / "legacy-run"
    directory.mkdir()
    manifest_path = directory / "input_manifest.json"
    manifest_path.write_text(json.dumps(data))
    original = manifest_path.read_bytes()
    (directory / "status.json").write_text(
        json.dumps({"state": "prepared", "run_id": manifest.run_id})
    )
    config = yaml.safe_load(project.read_text())
    config["model"].update(name="gpt-6-luna", reasoning_effort="none")
    project.write_text(yaml.safe_dump(config))
    run_exercise(
        project,
        "frame_challenge",
        directory,
        [],
        False,
        True,
        Decimal("1"),
        client=fake_client_type([_analysis(manifest)]),
    )
    request = json.loads((directory / "analyst_request.json").read_text())
    assert request["model"] == "gpt-4.1-mini-2025-04-14"
    assert "reasoning" not in request
    assert manifest.citation_format == "line_spans"
    assert "EvidenceCitation" in request["text"]["format"]["schema"]["$defs"]
    assert "PassageReference" not in request["text"]["format"]["schema"]["$defs"]
    source = json.loads(request["input"][0]["content"])["sources"][0]
    assert "content" in source
    assert "passages" not in source
    assert manifest_path.read_bytes() == original


def test_invalid_reasoning_effort_fails_at_configuration_boundary(project):
    config = yaml.safe_load(project.read_text())
    config["model"]["reasoning_effort"] = "strong"
    project.write_text(yaml.safe_dump(config))
    with pytest.raises(ValidationError, match="reasoning_effort"):
        load_config(project)
