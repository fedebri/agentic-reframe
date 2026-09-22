"""Exercise the four-perspective workflow with real files and a local SDK transport."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from openai import OpenAI
from test_first_pass import api_response

from agentic_dt.cli import main
from agentic_dt.framing import REASONING_ROLES, SYNTHESIZER, run_framing
from agentic_dt.graph import replay
from agentic_dt.orchestrator import run_first_pass
from agentic_dt.schemas import FramingSynthesis, LogEvent, framing_response_model

ROOT = Path(__file__).resolve().parents[1]


def role_output(agent_id):
    """One distinct insight per role, with deliberately colliding local IDs."""
    return {
        "agent_id": agent_id,
        "exercise_id": "frame_challenge",
        "takeaways": [
            {
                "takeaway_id": "candidate",
                "agent_id": agent_id,
                "exercise_id": "frame_challenge",
                "claim": f"Fictional {agent_id} perspective on workshop participation.",
                "claim_type": "hypothesis",
                "evidence_refs": ["brief"],
                "confidence": 0.5,
                "validation_status": "proposed",
                "public_reasoning_summary": "An interpretation of the fictional brief.",
                "open_questions": ["What would participants say?"],
            }
        ],
    }


@pytest.fixture
def continuation(tmp_path):
    config = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    config["paths"]["brief"] = str(ROOT / "docs/examples/library_brief.md")
    for agent in [*config["agents"]["reasoning"], config["agents"]["synthesis"]]:
        agent["profile"] = str(ROOT / agent["profile"])
    config["exercise_registry"][0]["source"] = str(
        ROOT / "exercises/1_frame_challenge.md"
    )
    config_path = tmp_path / "config/project.yaml"
    config_path.parent.mkdir()
    config_path.write_text(yaml.safe_dump(config))
    prior = run_first_pass(config_path, None, False, None)
    response = json.dumps(role_output("systems_strategist"))
    (prior / "response.json").write_text(response)
    (prior / "status.json").write_text(
        json.dumps({"run_id": prior.name, "state": "completed"})
    )
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "run_id": prior.name,
                "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                "reviewer_id": "test_human",
                "retained_claim_ids": ["candidate"],
                "public_reasoning_summary": "Retain all original claims for inquiry.",
                "qualification": "Early framing is provisional, not verified.",
            }
        )
    )
    return config_path, prior, review


@pytest.fixture
def synthesis_output():
    output = role_output(SYNTHESIZER)
    # Only one role informs the selected frame. Others must still survive.
    output["takeaways"][0]["derived_from"] = ["opportunity_scout:candidate"]
    output["framed_challenge_id"] = "candidate"
    output["conflicts"] = [
        {
            "source_id": "human_interpreter:candidate",
            "target_id": "operational_realist:candidate",
            "classification": "productive_tension",
            "public_reasoning_summary": "Preserve differing fictional priorities.",
        }
    ]
    return output


def install_transport(monkeypatch, synthesis_output, failure=None):
    """Route actual SDK calls locally and retain exact payloads for assertions."""
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 1000})
        agent = payload["text"]["format"]["schema"]["properties"]["agent_id"]["const"]
        output = synthesis_output if agent == SYNTHESIZER else role_output(agent)
        if failure == agent:
            output["takeaways"][0]["evidence_refs"] = ["invented_interview"]
        if failure == "wrong_role" and agent == "human_interpreter":
            output = role_output("operational_realist")
        return httpx.Response(200, json=api_response(output))

    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        return OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-log")
    monkeypatch.setattr("agentic_dt.framing.OpenAI", factory)
    return calls


def test_preview_reuses_original_and_keeps_reasoning_isolated(
    continuation, monkeypatch
):
    config, prior, review = continuation

    def forbidden(**kwargs):
        pytest.fail("Preview cannot create a client")

    monkeypatch.setattr("agentic_dt.framing.OpenAI", forbidden)
    directory = run_framing(config, prior, review, False, None)
    assert (directory / "systems_strategist/response.json").read_bytes() == (
        prior / "response.json"
    ).read_bytes()
    assert len(list(directory.glob("*/request.json"))) == 3
    assert not (directory / "provisional_report.md").exists()
    assert not (config.parent.parent / "outputs/graph").exists()
    for agent in REASONING_ROLES[1:]:
        request = json.loads((directory / agent / "request.json").read_text())
        payload = json.loads(request["input"][0]["content"])
        assert set(payload) == {"brief"}
        assert "human_review" not in json.dumps(request)
        assert "tools" not in request
        model = framing_response_model(agent)
        assert request["text"]["format"]["schema"] == model.model_json_schema()
        manifest = json.loads((directory / agent / "input_manifest.json").read_text())
        assert manifest["synthesis_context"] is None
        assert set(manifest["sources"]) == {"brief", "profile", "exercise"}
        assert manifest["prior_claims"] == []


def test_success_retains_minority_claims_review_and_provenance(
    continuation, synthesis_output, monkeypatch
):
    config, prior, review = continuation
    original = (prior / "response.json").read_bytes()
    calls = install_transport(monkeypatch, synthesis_output)
    directory = run_framing(config, prior, review, True, Decimal("0.10"))
    assert (prior / "response.json").read_bytes() == original
    generation = [
        payload for path, payload in calls if not path.endswith("input_tokens")
    ]
    assert len(generation) == 4
    assert all("tools" not in payload for payload in generation)
    source_hashes = {
        json.loads(payload["input"][0]["content"])["brief"]["content_sha256"]
        for payload in generation
    }
    assert len(source_hashes) == 1
    for payload in generation[:3]:
        assert set(json.loads(payload["input"][0]["content"])) == {"brief"}
    synthesis_input = json.loads(generation[-1]["input"][0]["content"])
    assert set(synthesis_input["reasoning_outputs"]) == set(REASONING_ROLES)
    assert synthesis_input["human_review"] == json.loads(review.read_text())
    assert synthesis_input["brief"]["snapshot"].startswith("# Fictional")
    graph_path = (
        config.parent.parent
        / "outputs/graph"
        / directory.name
        / "provenance_events.jsonl"
    )
    graph = replay(graph_path)
    assert len(graph.claims) == 5
    assert all(f"{role}:candidate" in graph.claims for role in REASONING_ROLES)
    assert set(graph.statuses.values()) == {"proposed"}
    assert graph.reviews["systems_strategist:candidate"] == "accepted"
    assert graph.reviews["sovereign_synthesizer:candidate"] == "pending"
    assert not graph.reportable_claims()
    assert any(edge.relation == "contradicts" for edge in graph.edges.values())
    report = (directory / "provisional_report.md").read_text()
    assert all(claim_id in report for claim_id in graph.claims)
    assert "Early framing is provisional" in report
    assert "productive_tension" in report
    logs = (
        config.parent.parent / "outputs/logs" / directory.name / "run_events.jsonl"
    ).read_text()
    assert "test-secret-never-log" not in logs
    events = [LogEvent.model_validate_json(line) for line in logs.splitlines()]
    assert (
        set(next(e.graph_event_ids for e in events if e.event_type == "graph_appended"))
        == graph.event_ids
    )
    assert events[-1].event_type == "completed"


@pytest.mark.parametrize(
    "failure", ["human_interpreter", "operational_realist", "wrong_role"]
)
def test_required_agent_failure_blocks_synthesis_and_graph(
    continuation, synthesis_output, monkeypatch, failure
):
    config, prior, review = continuation
    calls = install_transport(monkeypatch, synthesis_output, failure)
    with pytest.raises(ValueError):
        run_framing(config, prior, review, True, Decimal("0.10"))
    directory = next(prior.parent.glob("framing-*"))
    assert json.loads((directory / "status.json").read_text())["state"] == "failed"
    assert not (directory / SYNTHESIZER).exists()
    assert not (directory / "provisional_report.md").exists()
    assert not (config.parent.parent / "outputs/graph").exists()
    assert len(calls) == (4 if failure == "operational_realist" else 2)


@pytest.mark.parametrize(
    "failure",
    ["premise", "conflict", "self_conflict", "frame", "evidence", "promotion"],
)
def test_invalid_synthesis_never_writes_graph_or_report(
    continuation, synthesis_output, monkeypatch, failure
):
    if failure == "premise":
        synthesis_output["takeaways"][0]["derived_from"] = ["unknown:candidate"]
    elif failure == "conflict":
        synthesis_output["conflicts"][0]["source_id"] = "unknown:candidate"
    elif failure == "self_conflict":
        synthesis_output["conflicts"][0]["source_id"] = synthesis_output["conflicts"][
            0
        ]["target_id"]
    elif failure == "frame":
        synthesis_output["framed_challenge_id"] = "unknown"
    elif failure == "evidence":
        synthesis_output["takeaways"][0]["evidence_refs"] = ["human_review"]
    elif failure == "promotion":
        synthesis_output["takeaways"][0]["validation_status"] = "supported"
    config, prior, review = continuation
    install_transport(monkeypatch, synthesis_output)
    with pytest.raises(ValueError):
        run_framing(config, prior, review, True, Decimal("0.10"))
    assert not (config.parent.parent / "outputs/graph").exists()
    directory = next(prior.parent.glob("framing-*"))
    assert not (directory / "provisional_report.md").exists()
    assert not (directory / SYNTHESIZER / "response.json").exists()


@pytest.mark.parametrize("budget,completed", [("0.02", 1), ("0.05", 3)])
def test_budget_is_shared_across_agents(
    continuation, synthesis_output, monkeypatch, budget, completed
):
    config, prior, review = continuation
    calls = install_transport(monkeypatch, synthesis_output)
    # Each call reserves $0.0136 at these fixture token counts, including retry.
    with pytest.raises(ValueError, match="budget"):
        run_framing(config, prior, review, True, Decimal(budget))
    assert (
        len([path for path, _ in calls if not path.endswith("input_tokens")])
        == completed
    )
    assert not (config.parent.parent / "outputs/graph").exists()


@pytest.mark.parametrize("failure", ["hash", "run", "claims", "status", "snapshot"])
def test_invalid_import_or_review_fails_before_calls(continuation, failure):
    config, prior, review_path = continuation
    review = json.loads(review_path.read_text())
    if failure == "hash":
        review["response_sha256"] = "wrong"
    elif failure == "run":
        review["run_id"] = "wrong"
    elif failure == "claims":
        review["retained_claim_ids"] = ["unknown"]
    elif failure == "status":
        (prior / "status.json").write_text(json.dumps({"state": "failed"}))
    elif failure == "snapshot":
        path = prior / "input_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["sources"]["brief"]["snapshot"] = "tampered"
        path.write_text(json.dumps(manifest))
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError):
        run_framing(config, prior, review_path, False, None)
    assert not list(prior.parent.glob("framing-*"))


def test_all_model_schemas_are_strict_and_required():
    for model in [framing_response_model("human_interpreter"), FramingSynthesis]:
        schema = model.model_json_schema()
        for record in [schema, *schema["$defs"].values()]:
            assert record["additionalProperties"] is False
            assert set(record["required"]) == set(record["properties"])
            assert all(
                "default" not in value for value in record["properties"].values()
            )


def test_cli_preview(continuation, capsys):
    config, prior, review = continuation
    assert (
        main(
            [
                "frame",
                "--config",
                str(config),
                "--from-first-pass",
                str(prior),
                "--review",
                str(review),
            ]
        )
        == 0
    )
    assert "Preview only" in capsys.readouterr().out


@pytest.mark.parametrize(
    "budget", [None, Decimal("0"), Decimal("NaN"), Decimal("Infinity")]
)
def test_live_requires_finite_budget(continuation, budget):
    config, prior, review = continuation
    with pytest.raises(ValueError, match="positive, finite"):
        run_framing(config, prior, review, True, budget)


def test_missing_key_records_failed_run(continuation, monkeypatch):
    config, prior, review = continuation
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        run_framing(config, prior, review, True, Decimal("0.10"))
    directory = next(prior.parent.glob("framing-*"))
    assert json.loads((directory / "status.json").read_text())["state"] == "failed"
    assert not (config.parent.parent / "outputs/graph").exists()


def test_continuation_uses_frozen_inputs_not_changed_files(continuation):
    config, prior, review = continuation
    data = yaml.safe_load(config.read_text())
    data["paths"]["brief"] = "missing-brief.md"
    data["exercise_registry"][0]["source"] = "missing/1_frame_challenge.md"
    data["agents"]["reasoning"][0]["profile"] = "missing-profile.md"
    config.write_text(yaml.safe_dump(data))
    directory = run_framing(config, prior, review, False, None)
    old = json.loads((prior / "input_manifest.json").read_text())["sources"]
    for agent in REASONING_ROLES[1:]:
        manifest = json.loads((directory / agent / "input_manifest.json").read_text())
        assert manifest["sources"]["brief"] == old["brief"]
        assert manifest["sources"]["exercise"] == old["exercise"]


def test_repeated_invocation_preserves_existing_graph(
    continuation, synthesis_output, monkeypatch
):
    config, prior, review = continuation
    install_transport(monkeypatch, synthesis_output)
    first = run_framing(config, prior, review, True, Decimal("0.10"))
    path = (
        config.parent.parent / "outputs/graph" / first.name / "provenance_events.jsonl"
    )
    original = path.read_bytes()
    second = run_framing(config, prior, review, True, Decimal("0.10"))
    assert first != second
    assert path.read_bytes() == original
    assert len(list(path.parent.parent.glob("*/provenance_events.jsonl"))) == 2
