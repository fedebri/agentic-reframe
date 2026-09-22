"""Tests of the input boundary using real temporary files and YAML."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agentic_dt.cli import main
from agentic_dt.config import load_config
from agentic_dt.inputs import load_inputs

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "brief.md").write_text("# Fictional challenge\n", encoding="utf-8")
    (tmp_path / "agent.md").write_text("# Role\n", encoding="utf-8")
    for order in (1, 2, 10):
        (tmp_path / f"{order}_exercise.md").write_text(
            f"# Exercise {order}\n\nIntact **Markdown**.\n", encoding="utf-8"
        )
    data = {
        "paths": {"brief": "brief.md"},
        "agents": {
            "reasoning": [{"id": "analyst", "profile": "agent.md"}],
            "synthesis": {"id": "synthesizer", "profile": "agent.md"},
        },
        "exercise_registry": [
            {"id": f"exercise_{n}", "order": n, "source": f"{n}_exercise.md"}
            for n in (10, 2, 1)
        ],
    }
    path = tmp_path / "config/project.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path, data


def test_numeric_order_and_intact_markdown_without_optional_sources(project):
    path, data = project
    data["exercise_registry"][0]["source_material"] = ["missing.pdf", "missing.html"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    inventory = load_inputs(load_config(path), path.parent.parent)
    assert list(inventory.exercises) == ["exercise_1", "exercise_2", "exercise_10"]
    assert inventory.exercises["exercise_2"].text == (
        "# Exercise 2\n\nIntact **Markdown**.\n"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "exercise_2", "duplicate id"),
        ("order", 2, "duplicate order"),
        ("order", 3, "disagrees"),
        ("order", "10", "valid integer"),
        ("source", "10_exercise.pdf", "expected N_name.md"),
    ],
)
def test_invalid_exercise_registry(project, field, value, message):
    path, data = project
    data["exercise_registry"][0][field] = value
    if message == "duplicate order":
        data["exercise_registry"][0]["source"] = "2_exercise.md"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        load_config(path)


def test_duplicate_agent_ids(project):
    path, data = project
    data["agents"]["synthesis"]["id"] = "analyst"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="duplicate IDs"):
        load_config(path)


@pytest.mark.parametrize("target", ["brief", "profile", "exercise"])
def test_missing_required_input_has_path_and_nonzero_exit(project, capsys, target):
    path, data = project
    if target == "brief":
        data["paths"]["brief"] = "missing.md"
    elif target == "profile":
        data["agents"]["reasoning"][0]["profile"] = "missing.md"
    else:
        data["exercise_registry"][0]["source"] = "10_missing.md"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["validate", "--config", str(path)])
    assert error.value.code == 2
    assert "missing.md" in capsys.readouterr().err


@pytest.mark.parametrize("content", ["paths: [", "[]", "{}"])
def test_malformed_or_incomplete_config(project, capsys, content):
    path, _ = project
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["validate", "--config", str(path)])
    assert error.value.code == 2
    assert str(path) in capsys.readouterr().err


def test_empty_input_is_rejected(project):
    path, _ = project
    (path.parent.parent / "brief.md").write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="Input file is empty.*brief.md"):
        load_inputs(load_config(path), path.parent.parent)


def test_override_and_paths_are_relative_to_project_not_working_directory(
    project, tmp_path
):
    path, _ = project
    override = path.parent.parent / "alternate.md"
    override.write_text("# Alternate fictional brief", encoding="utf-8")
    other_directory = tmp_path / "different_working_directory"
    other_directory.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentic_dt.cli",
            "validate",
            "--config",
            str(path),
            "--brief",
            "alternate.md",
        ],
        cwd=other_directory,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f"Brief: {override}" in result.stdout
    assert result.stdout.index("exercise_2:") < result.stdout.index("exercise_10:")


def test_repository_inventory():
    config = load_config(REPO_ROOT / "config/project.yaml")
    inventory = load_inputs(config, REPO_ROOT, Path("docs/examples/library_brief.md"))
    assert len(inventory.agents) == 5
    assert len(inventory.exercises) == 13
    assert list(inventory.exercises)[-1] == "value_proposition_canvas"
    assert "fictional software test fixture" in inventory.brief.text
