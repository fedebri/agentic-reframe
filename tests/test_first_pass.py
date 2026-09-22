"""Use the real SDK against a local HTTP transport; no external calls or charges."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from openai import APIStatusError, APITimeoutError, OpenAI

from agentic_dt.cli import main
from agentic_dt.config import ModelSettings, load_config
from agentic_dt.inputs import load_first_pass_sources
from agentic_dt.model import generate_response
from agentic_dt.orchestrator import run_first_pass
from agentic_dt.schemas import FirstPassResponse, LogEvent

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    data = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    data["paths"]["brief"] = str(ROOT / "docs/examples/library_brief.md")
    data["agents"]["reasoning"][0]["profile"] = str(ROOT / "agents/analyst.md")
    data["exercise_registry"][0]["source"] = str(
        ROOT / "exercises/1_frame_challenge.md"
    )
    # All other input paths remain relative and absent in this isolated project.
    path = tmp_path / "config/project.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.fixture
def settings():
    data = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    return ModelSettings.model_validate(data["first_pass_model"])


@pytest.fixture
def output():
    return {
        "agent_id": "systems_strategist",
        "exercise_id": "frame_challenge",
        "takeaways": [
            {
                "takeaway_id": "candidate_1",
                "agent_id": "systems_strategist",
                "exercise_id": "frame_challenge",
                "claim": "Investigate workshop access in the fictional scenario.",
                "claim_type": "hypothesis",
                "evidence_refs": ["brief"],
                "confidence": 0.5,
                "validation_status": "proposed",
                "public_reasoning_summary": "The brief names the audience.",
                "open_questions": ["Which barriers should fieldwork investigate?"],
            }
        ],
    }


def api_response(output, status="completed", refusal=False):
    """A minimal real Responses API wire fixture, including billable usage."""
    content = (
        [{"type": "refusal", "refusal": "Fixture refusal"}]
        if refusal
        else [
            {
                "type": "output_text",
                "text": output if isinstance(output, str) else json.dumps(output),
                "annotations": [],
            }
        ]
    )
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4.1-mini-2025-04-14",
        "status": status,
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 250,
            "total_tokens": 1250,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


@pytest.fixture
def request_payload(project):
    directory = run_first_pass(project, None, False, None)
    return json.loads((directory / "request.json").read_text())


def test_preview_is_scoped_and_makes_no_client(project, monkeypatch):
    def forbidden_client(**kwargs):
        pytest.fail("Preview must not create a provider client")

    monkeypatch.setattr("agentic_dt.orchestrator.OpenAI", forbidden_client)
    directory = run_first_pass(project, None, False, None)
    manifest = json.loads((directory / "input_manifest.json").read_text())
    assert set(manifest["sources"]) == {"brief", "profile", "exercise"}
    assert manifest["assigned_evidence_ids"] == ["brief"]
    assert manifest["tools"] == []
    assert manifest["prior_claims"] == []
    assert manifest["sources"]["brief"]["snapshot"].startswith("# Fictional")
    assert not (directory / "response.json").exists()
    assert json.loads((directory / "status.json").read_text())["state"] == "prepared"


def test_scoped_loader_rejects_oversized_input(project):
    with pytest.raises(ValueError, match="exceed 20 bytes"):
        load_first_pass_sources(load_config(project), project.parent.parent, None, 20)


def test_schema_is_strict_and_all_fields_required():
    schema = FirstPassResponse.model_json_schema()
    for record in [schema, *schema["$defs"].values()]:
        assert record["additionalProperties"] is False
        assert set(record["required"]) == set(record["properties"])
        assert not any("default" in prop for prop in record["properties"].values())


def test_request_schema_requires_assigned_origins(request_payload):
    schema = request_payload["text"]["format"]["schema"]
    for record in [schema, schema["$defs"]["ProposedClaim"]]:
        assert record["properties"]["agent_id"]["const"] == "systems_strategist"
        assert record["properties"]["exercise_id"]["const"] == "frame_challenge"


def test_success_uses_counted_payload_and_no_tools(settings, output, request_payload):
    calls, logs = [], []

    def handler(request):
        calls.append(json.loads(request.content))
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        return httpx.Response(
            200, json=api_response(output), headers={"x-request-id": "req_fixture"}
        )

    with OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        result = generate_response(
            client,
            request_payload,
            settings,
            Decimal("0.10"),
            lambda event, **data: logs.append((event, data)),
            response_model=FirstPassResponse,
        )
    assert result.takeaways[0].validation_status == "proposed"
    assert len(calls) == 2
    assert all(calls[1][key] == value for key, value in calls[0].items())
    assert calls[1]["store"] is False
    assert calls[1]["service_tier"] == "default"
    assert calls[1]["max_output_tokens"] == settings.max_output_tokens
    assert "tools" not in calls[1]
    received = next(data for event, data in logs if event == "response_received")
    assert received["usage"]["input_tokens"] == 1000
    assert received["estimated_cost_usd"] == "0.0008"
    assert received["request_id"] == "req_fixture"


@pytest.mark.parametrize(
    "count,budget,message",
    [
        (1000, "0.0001", "Maximum estimated cost"),
        (20001, "0.10", "limit is 20000"),
    ],
)
def test_limits_block_generation(settings, request_payload, count, budget, message):
    def handler(request):
        assert request.url.path.endswith("input_tokens")
        return httpx.Response(200, json={"input_tokens": count})

    with OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(ValueError, match=message):
            generate_response(
                client,
                request_payload,
                settings,
                Decimal(budget),
                lambda *args, **kwargs: None,
                response_model=FirstPassResponse,
            )


@pytest.mark.parametrize("failure", ["429", "500", "timeout", "401"])
def test_retry_exhaustion_is_bounded(settings, request_payload, failure, monkeypatch):
    attempts, logs = [], []
    monkeypatch.setattr("agentic_dt.model.time.sleep", lambda seconds: None)

    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        attempts.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Fixture timeout", request=request)
        return httpx.Response(
            int(failure), json={"error": {"message": "Fixture failure"}}
        )

    with OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises((APIStatusError, APITimeoutError)):
            generate_response(
                client,
                request_payload,
                settings,
                Decimal("0.10"),
                lambda event, **data: logs.append((event, data)),
                response_model=FirstPassResponse,
            )
    assert len(attempts) == (1 if failure == "401" else 2)
    assert sum(event == "retry_warning" for event, _ in logs) == (failure != "401")
    assert logs[-1][0] == "api_failed"
    assert logs[-1][1]["usage"] is None


@pytest.mark.parametrize(
    "case",
    [
        "malformed",
        "invented_source",
        "wrong_role",
        "wrong_exercise",
        "wrong_claim_role",
        "wrong_claim_exercise",
        "promoted",
        "refusal",
        "incomplete",
        "empty",
    ],
)
def test_invalid_output_is_rejected_after_usage_saved(
    settings, output, request_payload, case
):
    if case == "malformed":
        output = "not JSON"
    elif case == "invented_source":
        output["takeaways"][0]["evidence_refs"] = ["invented_interview"]
    elif case == "wrong_role":
        output["agent_id"] = output["takeaways"][0]["agent_id"] = "other"
    elif case == "wrong_exercise":
        output["exercise_id"] = output["takeaways"][0]["exercise_id"] = "other"
    elif case == "wrong_claim_role":
        output["takeaways"][0]["agent_id"] = "other"
    elif case == "wrong_claim_exercise":
        output["takeaways"][0]["exercise_id"] = "other"
    elif case == "promoted":
        output["takeaways"][0]["validation_status"] = "supported"
    elif case == "empty":
        output["takeaways"] = []
    attempts, logs = [], []

    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        attempts.append(request)
        return httpx.Response(
            200,
            json=api_response(
                output,
                status="incomplete" if case == "incomplete" else "completed",
                refusal=case == "refusal",
            ),
        )

    with OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(ValueError):
            generate_response(
                client,
                request_payload,
                settings,
                Decimal("0.10"),
                lambda event, **data: logs.append((event, data)),
                response_model=FirstPassResponse,
            )
    assert len(attempts) == 1
    assert logs[-1][0] == "response_received"
    assert logs[-1][1]["usage"]["output_tokens"] == 250


@pytest.mark.parametrize("valid", [True, False])
def test_live_workflow_artifacts_and_no_graph_mutations(
    project, output, monkeypatch, valid
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-log")
    if not valid:
        output["takeaways"][0]["evidence_refs"] = ["invented"]

    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        return httpx.Response(200, json=api_response(output))

    def client_factory(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["timeout"] == 60
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        return OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr("agentic_dt.orchestrator.OpenAI", client_factory)
    if valid:
        run_first_pass(project, None, True, Decimal("0.10"))
    else:
        with pytest.raises(ValueError, match="only brief"):
            run_first_pass(project, None, True, Decimal("0.10"))
    root = project.parent.parent
    status_file = next(root.glob("outputs/exercises/frame_challenge/*/status.json"))
    assert json.loads(status_file.read_text())["state"] == (
        "completed" if valid else "failed"
    )
    assert (status_file.parent / "response.json").exists() == valid
    assert (status_file.parent / "response.md").exists() == valid
    assert not (root / "outputs/graph").exists()
    log = next(root.glob("outputs/logs/*/run_events.jsonl")).read_text()
    for line in log.splitlines():
        LogEvent.model_validate_json(line)
    assert "test-secret-never-log" not in log
    assert json.loads(log.splitlines()[-1])["event_type"] == (
        "completed" if valid else "failed"
    )


def test_missing_key_records_failure(project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        run_first_pass(project, None, True, Decimal("0.10"))
    status = next(
        project.parent.parent.glob("outputs/exercises/frame_challenge/*/status.json")
    )
    assert json.loads(status.read_text())["state"] == "failed"


@pytest.mark.parametrize(
    "budget", [None, Decimal("0"), Decimal("NaN"), Decimal("Infinity")]
)
def test_live_requires_budget(project, budget):
    with pytest.raises(ValueError, match="requires a positive"):
        run_first_pass(project, None, True, budget)


def test_cli_preview(project, capsys):
    assert main(["first-pass", "--config", str(project)]) == 0
    assert "Preview only" in capsys.readouterr().out


def test_cli_invalid_budget_is_readable(project, capsys):
    with pytest.raises(SystemExit) as error:
        main(["first-pass", "--config", str(project), "--live", "--budget-usd", "oops"])
    assert error.value.code == 2
    assert "decimal amount" in capsys.readouterr().err


def test_transient_failure_then_success(settings, output, request_payload, monkeypatch):
    attempts, logs = [], []
    monkeypatch.setattr("agentic_dt.model.time.sleep", lambda seconds: None)

    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(
                429, json={"error": {"message": "Fixture rate limit"}}
            )
        return httpx.Response(200, json=api_response(output))

    with OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        result = generate_response(
            client,
            request_payload,
            settings,
            Decimal("0.10"),
            lambda event, **data: logs.append((event, data)),
            response_model=FirstPassResponse,
        )
    assert result.takeaways
    assert len(attempts) == 2
    assert sum(event == "retry_warning" for event, _ in logs) == 1
