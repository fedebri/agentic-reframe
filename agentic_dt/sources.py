"""Explicit source selection and immutable snapshot construction."""

import hashlib
from itertools import groupby
from pathlib import Path

from .schemas import EvidenceCitation, FrozenSource


def freeze_source(path: Path, source_id: str, max_bytes: int) -> FrozenSource:
    """Read one assigned UTF-8 file without scanning adjacent directories."""
    path = path.resolve()
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError(f"{path}: {len(raw)} bytes exceeds limit {max_bytes}")
    content = raw.decode("utf-8")
    return FrozenSource(
        source_id=source_id,
        source_path=str(path),
        content=content,
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )


def file_sha256(path: Path) -> str:
    """Hash exact saved bytes for review and resume binding."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_passages(source: FrozenSource) -> dict[str, EvidenceCitation]:
    """Assign source-local IDs to blank-line-separated blocks in a snapshot."""
    passages = {}
    groups = groupby(
        enumerate(source.content.splitlines(), start=1),
        key=lambda item: bool(item[1].strip()),
    )
    for nonempty, group in groups:
        if nonempty:
            block = list(group)
            passages[f"p{len(passages) + 1}"] = EvidenceCitation(
                source_id=source.source_id,
                start_line=block[0][0],
                end_line=block[-1][0],
                quote="\n".join(line for _, line in block).strip(),
            )
    return passages


def indexed_sources(sources: list[FrozenSource]) -> list[dict[str, object]]:
    """Present every source block once, with IDs instead of model-counted lines."""
    return [
        {
            **source.model_dump(exclude={"content"}),
            "passages": [
                {"passage_id": passage_id, "text": citation.quote}
                for passage_id, citation in index_passages(source).items()
            ],
        }
        for source in sources
    ]


def validate_citations(
    citations: list[EvidenceCitation], sources: dict[str, FrozenSource]
) -> None:
    """Check source identity, line bounds, and exact quoted text at a boundary."""
    for citation in citations:
        source = sources[citation.source_id]
        lines = source.content.splitlines()
        if not 1 <= citation.start_line <= citation.end_line <= len(lines):
            raise ValueError(f"{citation.source_id}: citation line range is invalid")
        passage = "\n".join(lines[citation.start_line - 1 : citation.end_line]).strip()
        if passage != citation.quote:
            raise ValueError(
                f"{citation.source_id}: quoted passage does not match source"
            )
