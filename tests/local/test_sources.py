"""Source-local passage IDs remove model-generated quotation bookkeeping."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from test_workflow import _analysis

from agentic_dt.evals import evaluate_run
from agentic_dt.review import export_review
from agentic_dt.schemas import EvidenceCitation, RunManifest
from agentic_dt.sources import freeze_source, index_passages, validate_citations
from agentic_dt.workflow import run_exercise


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_passages_preserve_blocks_and_exact_source_locations(tmp_path, newline):
    text = (
        "# Brief\n\n"
        "## Challenge\n \n"
        "An audience's experience\ncontinues on this line.\n\n"
        "- First constraint.\n- Second constraint.\n\n"
        "An audience's experience\ncontinues on this line.\n"
    ).replace("\n", newline)
    path = tmp_path / "brief.md"
    path.write_bytes(text.encode("utf-8"))
    source = freeze_source(path, "brief:snapshot", 10000)
    passages = index_passages(source)
    assert list(passages) == ["p1", "p2", "p3", "p4", "p5"]
    assert [(p.start_line, p.end_line) for p in passages.values()] == [
        (1, 1),
        (3, 3),
        (5, 6),
        (8, 9),
        (11, 12),
    ]
    assert passages["p3"].quote == "An audience's experience\ncontinues on this line."
    assert passages["p4"].quote == "- First constraint.\n- Second constraint."
    assert passages["p3"].quote == passages["p5"].quote
    assert index_passages(source) == passages
    validate_citations(list(passages.values()), {source.source_id: source})
    assert path.read_bytes() == text.encode("utf-8")


def test_empty_source_has_no_invented_passages(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text(" \n\n")
    assert index_passages(freeze_source(path, "empty", 1000)) == {}


def test_line_citation_validation_remains_strict(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("First line.\nSecond line.\n")
    source = freeze_source(path, "brief:snapshot", 1000)
    citation = EvidenceCitation(
        source_id=source.source_id, start_line=1, end_line=1, quote="Invented text."
    )
    with pytest.raises(ValueError, match="does not match source"):
        validate_citations([citation], {source.source_id: source})


def test_library_passage_resolves_to_lines_8_to_10_and_resumes_frozen(
    project, tmp_path, fake_client_type
):
    root = Path(__file__).resolve().parents[2]
    brief_path = project.parent.parent / "docs" / "brief.md"
    brief = (root / "docs" / "examples" / "library_brief.md").read_text()
    brief_path.write_text(brief)
    directory = run_exercise(
        project,
        "frame_challenge",
        tmp_path / "library-run",
        [Path("evidence.md")],
        False,
        False,
        None,
        human_frame_path=Path("human_frame.yaml"),
    )
    manifest_path = directory / "input_manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = RunManifest.model_validate_json(original_manifest)
    request_path = directory / "analyst_request.json"
    original_request = request_path.read_bytes()
    request = json.loads(original_request)
    source = json.loads(request["input"][0]["content"])["sources"][0]
    expected = "\n".join(brief.splitlines()[7:10])
    assert source["passages"][3] == {"passage_id": "p4", "text": expected}
    response = _analysis(manifest)
    response["claims"][0]["citations"][0]["passage_id"] = "p4"
    response["claims"][1]["evidence_refs"] = [manifest.sources[1].source_id]
    response["claims"][1]["citations"][0]["source_id"] = manifest.sources[1].source_id
    client = fake_client_type([response])
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
    saved = json.loads((directory / "analyst_response.json").read_text())
    citation = saved["claims"][0]["citations"][0]
    assert citation == {
        "source_id": manifest.sources[0].source_id,
        "start_line": 8,
        "end_line": 10,
        "quote": expected,
    }
    assert saved["claims"][1]["citations"][0] == {
        "source_id": manifest.sources[1].source_id,
        "start_line": 1,
        "end_line": 1,
        "quote": "Participant note.",
    }
    assert (
        "\n".join(f"> {line}" for line in expected.splitlines())
        in (directory / "comparison.md").read_text()
    )
    review_path = export_review(directory, tmp_path / "review.yaml", "tester")
    review = yaml.safe_load(review_path.read_text())
    assert review["decisions"][0]["citations"][0] == citation
    evaluation = json.loads(evaluate_run(directory, tmp_path / "eval.json").read_text())
    assert evaluation["passage_accuracy"] == 1

    original_log = (directory / "run_events.jsonl").read_bytes()
    brief_path.write_text("An unrelated later revision of the brief.")
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
    assert manifest_path.read_bytes() == original_manifest
    assert request_path.read_bytes() == original_request
    assert (directory / "run_events.jsonl").read_bytes() == original_log
    assert not Path(manifest.ledger_path).exists()
