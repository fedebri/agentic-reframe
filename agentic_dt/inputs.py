"""Load the explicitly configured inputs without executing their instructions."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .schemas import Evidence


@dataclass(frozen=True)
class Document:
    """A readable source and its intact UTF-8 content."""

    path: Path
    text: str


@dataclass(frozen=True)
class InputInventory:
    """Configured brief, role profiles, and exercises in execution order."""

    brief: Document
    agents: dict[str, Document]
    exercises: dict[str, Document]


def load_source(path: Path, source_id: str, max_bytes: int) -> Evidence:
    """Retain a bounded UTF-8 source snapshot and its provenance."""
    path = path.resolve()
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Assigned inputs exceed {max_bytes} bytes at {path}")
    snapshot = raw.decode("utf-8")
    if not snapshot.strip():
        raise ValueError(f"Input file is empty: {path}")
    return Evidence(
        source_id=source_id,
        source_path=str(path),
        snapshot=snapshot,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        start_line=1,
        end_line=len(snapshot.splitlines()),
    )


def load_first_pass_sources(
    config: ProjectConfig, project_root: Path, brief: Path | None, max_bytes: int
) -> dict[str, Evidence]:
    """Read exactly the brief, Systems Strategist profile, and exercise 1.

    Other roles, human input, and prior graph history are deliberately unassigned.
    Evidence records retain complete snapshots; profile/exercise are instructions,
    so only the brief's source ID is eligible as a factual citation during the
    first pass.
    """
    agents = {agent.id: agent for agent in config.agents.reasoning}
    exercises = {exercise.id: exercise for exercise in config.exercise_registry}
    exercise = exercises["frame_challenge"]
    if exercise.order != 1:
        raise ValueError("frame_challenge must be exercise 1 for the first pass")
    assigned = {
        "brief": brief if brief is not None else config.paths.brief,
        "profile": agents["systems_strategist"].profile,
        "exercise": exercise.source,
    }
    sources = {}
    total_bytes = 0
    for source_id, relative_path in assigned.items():
        path = project_root / relative_path
        source = load_source(path, source_id, max_bytes)
        total_bytes += len(source.snapshot.encode("utf-8"))
        if total_bytes > max_bytes:
            raise ValueError(f"Assigned inputs exceed {max_bytes} bytes at {path}")
        sources[source_id] = source
    return sources


def load_inputs(
    config: ProjectConfig, project_root: Path, brief: Path | None = None
) -> InputInventory:
    """Load required files relative to the project root.

    Absolute paths are accepted. Optional imported HTML/PDF sources and human
    evidence are not loaded by the inventory command. Profile and exercise text
    stay intact.
    """
    brief_path = project_root / (brief if brief is not None else config.paths.brief)
    brief_path = brief_path.resolve()
    brief_document = Document(brief_path, brief_path.read_text(encoding="utf-8"))
    agents = {}
    for agent in [*config.agents.reasoning, config.agents.synthesis]:
        path = (project_root / agent.profile).resolve()
        agents[agent.id] = Document(path, path.read_text(encoding="utf-8"))
    exercises = {}
    for exercise in sorted(config.exercise_registry, key=lambda item: item.order):
        path = (project_root / exercise.source).resolve()
        exercises[exercise.id] = Document(path, path.read_text(encoding="utf-8"))
    for document in [brief_document, *agents.values(), *exercises.values()]:
        if not document.text.strip():
            raise ValueError(f"Input file is empty: {document.path}")
    return InputInventory(brief_document, agents, exercises)
