import json
from pathlib import Path

from agentic_dt.graph import replay
from agentic_dt.tutorial import run_tutorial


def test_repository_tutorial_is_isolated_and_complete(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    output = run_tutorial(root / "config" / "project.yaml", tmp_path / "tutorial")
    assert (output / "ledger" / "events.jsonl").exists()
    assert (output / "eval_report.json").exists()
    assert (output / "reports" / "design_research_brief.md").exists()
    assert "No API call" in (output / "TUTORIAL.md").read_text()
    summary = json.loads((output / "tutorial_summary.json").read_text())
    state = replay(output / "ledger" / "events.jsonl")
    assert len(state.completed_runs) == 2
    assert len(state.human_frames) == 2
    assert len(state.reflections) == 2
    assert len(state.applied_reviews) == 3
    assert state.statuses[summary["deprecated_claim"]] == "deprecated"
    assert state.reviews[summary["deprecated_claim"]] == "rejected"
    assert summary["new_observation"] in {
        claim.claim_id for claim in state.reportable_claims()
    }
    assert summary["claim_of_improved_human_reasoning"] is None
    assert (
        "independent human interpretation"
        in (output / "follow_up_run" / "comparison.md").read_text().lower()
    )
    assert (
        "Human framing decisions"
        in (output / "reports" / "design_research_brief.md").read_text()
    )
