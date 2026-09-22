"""Verify provenance rules against real JSONL files, without model calls."""

import json

import pytest
from pydantic import ValidationError

from agentic_dt.demo import demo_events, run_demo
from agentic_dt.graph import EVENT_ADAPTER, append_events, replay
from agentic_dt.schemas import AgentResponse, Evidence


@pytest.fixture
def history(tmp_path):
    path = tmp_path / "graph/events.jsonl"
    initial, correction = demo_events("test-run")
    append_events(path, initial)
    return path, initial, correction


def test_append_preserves_history_and_replay_reproduces_state(history):
    path, _, correction = history
    original = path.read_bytes()
    state = append_events(path, correction)
    assert path.read_bytes().startswith(original)
    assert replay(path) == state
    assert len(state.claims) == 2
    assert state.claims["evenings_only"].validation_status == "proposed"
    assert state.statuses["evenings_only"] == "deprecated"
    assert [claim.takeaway_id for claim in state.reportable_claims()] == [
        "weekend_session"
    ]


def test_duplicate_event_rejected_without_writing(history):
    path, initial, _ = history
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Duplicate event ID"):
        append_events(path, [initial[0]])
    assert path.read_bytes() == original


def test_whole_batch_validated_before_writing(history):
    path, _, correction = history
    original = path.read_bytes()
    bad = correction[1].model_copy(update={"subject_id": "nonexistent"})
    with pytest.raises(ValueError, match="Unknown claim"):
        append_events(path, [correction[0], bad])
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "change, message",
    [
        ({"subject_id": "missing"}, "unknown claim"),
        ({"run_id": "another-run"}, "cannot enter graph"),
    ],
)
def test_unknown_edge_endpoint_and_cross_run_isolation(history, change, message):
    path, _, correction = history
    event = correction[0].model_dump(mode="json")
    if "subject_id" in change:
        event["payload"]["source_id"] = change["subject_id"]
    else:
        event.update(change)
    original = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        append_events(path, [EVENT_ADAPTER.validate_python(event)])
    assert path.read_bytes() == original


def test_unknown_evidence_and_duplicate_claim_ids(history):
    path, initial, _ = history
    event = initial[2].model_dump(mode="json")
    event["event_id"] = "new-event"
    with pytest.raises(ValueError, match="Duplicate graph subject"):
        append_events(path, [EVENT_ADAPTER.validate_python(event)])
    event["subject_id"] = event["payload"]["takeaway_id"] = "new-claim"
    event["payload"]["evidence_refs"] = ["invented-source"]
    with pytest.raises(ValueError, match="unknown evidence"):
        append_events(path, [EVENT_ADAPTER.validate_python(event)])


def test_deprecation_requires_edge_and_cannot_be_reversed(history):
    path, _, correction = history
    with pytest.raises(ValueError, match="deprecation requires"):
        append_events(path, [correction[1]])
    append_events(path, correction)
    event = correction[1].model_dump(mode="json")
    event["event_id"] = "resurrect"
    event["payload"]["status"] = "supported"
    with pytest.raises(ValueError, match="invalid status transition"):
        append_events(path, [EVENT_ADAPTER.validate_python(event)])


def test_invalidation_immediately_blocks_target_even_before_status_event(history):
    path, initial, correction = history
    fresh = path.parent / "edge-only.jsonl"
    append_events(fresh, initial[:9])
    state = append_events(fresh, [correction[0]])
    assert state.statuses["evenings_only"] == "supported"
    assert "evenings_only" not in [c.takeaway_id for c in state.reportable_claims()]


@pytest.mark.parametrize("relation", ["depends_on", "supports"])
def test_deprecated_premise_blocks_derived_conclusions(history, relation):
    path, initial, correction = history
    claim = initial[2].model_dump(mode="json")
    claim["event_id"] = "derived-claim-event"
    claim["subject_id"] = claim["payload"]["takeaway_id"] = "derived"
    status = initial[3].model_dump(mode="json")
    status.update(event_id="derived-status-event", subject_id="derived")
    review = initial[4].model_dump(mode="json")
    review.update(event_id="derived-review-event", subject_id="derived")
    edge = correction[0].model_dump(mode="json")
    edge.update(event_id="dependency-event", subject_id="dependency")
    source, target = ("derived", "evenings_only")
    if relation == "supports":
        source, target = target, source
    edge["payload"].update(source_id=source, target_id=target, relation=relation)
    append_events(
        path, [EVENT_ADAPTER.validate_python(e) for e in (claim, status, review, edge)]
    )
    state = append_events(path, correction)
    assert state.statuses["derived"] == "supported"
    assert "derived" not in [c.takeaway_id for c in state.reportable_claims()]


def test_review_is_separate_from_evidence_status(tmp_path):
    initial, _ = demo_events("review-test")
    path = tmp_path / "events.jsonl"
    # Evidence, proposed claim, then support; acceptance is the next event.
    state = append_events(path, initial[:4])
    assert state.statuses["evenings_only"] == "supported"
    assert state.reviews["evenings_only"] == "pending"
    assert not state.reportable_claims()
    state = append_events(path, initial[4:5])
    assert len(state.reportable_claims()) == 1
    reject = initial[4].model_dump(mode="json")
    reject["event_id"] = "reject-review"
    reject["payload"]["decision"] = "rejected"
    state = append_events(path, [EVENT_ADAPTER.validate_python(reject)])
    assert state.statuses["evenings_only"] == "supported"
    assert not state.reportable_claims()


def test_accepted_proposed_claim_is_not_reportable(tmp_path):
    initial, _ = demo_events("proposed-test")
    path = tmp_path / "events.jsonl"
    state = append_events(path, [*initial[:3], initial[4]])
    assert state.reviews["evenings_only"] == "accepted"
    assert not state.reportable_claims()


def test_accepted_tension_requires_contradiction(history, tmp_path):
    path, initial, _ = history
    event = initial[-1].model_dump(mode="json")
    event["event_id"] = "accept-tension"
    event["payload"]["status"] = "accepted_tension"
    state = append_events(path, [EVENT_ADAPTER.validate_python(event)])
    assert len(state.reportable_claims()) == 2
    other = tmp_path / "no-conflict.jsonl"
    append_events(other, initial[:8])
    with pytest.raises(ValueError, match="tension requires"):
        append_events(other, [EVENT_ADAPTER.validate_python(event)])


@pytest.mark.parametrize("status", ["proposed", "contested"])
def test_invalid_status_transitions(history, status):
    path, initial, _ = history
    event = initial[-1].model_dump(mode="json")
    event["event_id"] = "invalid-status"
    event["payload"]["status"] = status
    with pytest.raises(ValueError, match="invalid status transition"):
        append_events(path, [EVENT_ADAPTER.validate_python(event)])


@pytest.mark.parametrize("suffix", ['{"partial":', "{}\n"])
def test_corrupt_history_is_rejected_not_repaired(history, suffix):
    path, _, correction = history
    with path.open("a", encoding="utf-8") as stream:
        stream.write(suffix)
    corrupted = path.read_bytes()
    with pytest.raises(ValueError, match=str(path)):
        append_events(path, correction)
    assert path.read_bytes() == corrupted


def test_source_snapshot_hash_and_excerpt(history):
    _, initial, _ = history
    evidence = initial[0].payload.model_dump()
    assert (
        Evidence.model_validate(evidence).snapshot.splitlines()[1].startswith("Earlier")
    )
    with pytest.raises(ValidationError, match="hash mismatch"):
        Evidence.model_validate({**evidence, "snapshot": "Changed source"})
    with pytest.raises(ValidationError, match="line range"):
        Evidence.model_validate({**evidence, "end_line": 100})


def test_response_origin_and_confidence(history):
    _, initial, _ = history
    claim = initial[2].payload.model_dump()
    response = {
        "agent_id": claim["agent_id"],
        "exercise_id": claim["exercise_id"],
        "takeaways": [claim],
    }
    assert len(AgentResponse.model_validate(response).takeaways) == 1
    with pytest.raises(ValidationError, match="origin mismatch"):
        AgentResponse.model_validate({**response, "agent_id": "other-agent"})
    claim["confidence"] = 1.1
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(response)


def test_demo_repeat_creates_isolated_histories_and_structured_logs(tmp_path, capsys):
    graph_root, log_root = tmp_path / "graph", tmp_path / "logs"
    first = run_demo(graph_root, log_root)
    original = first.read_bytes()
    second = run_demo(graph_root, log_root)
    assert first != second
    assert first.read_bytes() == original
    assert replay(first).run_id != replay(second).run_id
    assert "Original history preserved: True" in capsys.readouterr().out
    log = json.loads((log_root / first.parent.name / "run_events.jsonl").read_text())
    assert log["validation_status"] == "completed"
    assert set(log["graph_event_ids"]) == replay(first).event_ids
