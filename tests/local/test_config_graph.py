import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_dt.config import load_config
from agentic_dt.graph import EVENT_ADAPTER, append_events, replay
from agentic_dt.schemas import FrozenSource


def test_configuration_is_complete_and_strict(project: Path) -> None:
    config = load_config(project)
    assert config.project.version == "2.0.0"
    text = project.read_text(encoding="utf-8") + "unknown: true\n"
    project.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_config(project)


def test_append_only_ledger_replays_and_rejects_mixed_ledgers(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    content = "source"
    source = FrozenSource(
        source_id="brief:1",
        source_path="brief.md",
        content=content,
        content_sha256=(
            "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d"
        ),
    )
    timestamp = datetime.now(timezone.utc)
    event = EVENT_ADAPTER.validate_python(
        {
            "event_id": "event-1",
            "ledger_id": "ledger-a",
            "timestamp": timestamp,
            "run_id": "run-1",
            "exercise_id": "frame_challenge",
            "subject_id": source.source_id,
            "event_type": "evidence_added",
            "payload": source.model_dump(),
        }
    )
    state = append_events(ledger, [event])
    assert state.evidence[source.source_id] == source
    assert replay(ledger).event_ids == {"event-1"}
    mixed = json.loads(event.model_dump_json())
    mixed.update(event_id="event-2", ledger_id="ledger-b", subject_id="brief:2")
    mixed["payload"]["source_id"] = "brief:2"
    with pytest.raises(ValueError, match="different ledgers"):
        append_events(ledger, [EVENT_ADAPTER.validate_python(mixed)])


def test_incomplete_ledger_record_fails_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    ledger.write_text('{"partial": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete final record"):
        replay(ledger)
