"""Bounded, immutable cohort snapshots for a small Workers-hosted pilot."""

import io
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from extensions.web.storage import WebStore

MAX_SNAPSHOT_BYTES = 12 * 1024 * 1024


class SnapshotStore(WebStore):
    """Use SQLite locally while the Durable Object serializes snapshot commits."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "web.sqlite3"
        root.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(
                Path(__file__).parents[1].joinpath("web/schema.sql").read_text()
            )

    def project_lock(self, project_id: str, *, shared: bool = False):
        """The host holds a Durable Object gate instead of an OS file lock."""
        return nullcontext()


def pack_snapshot(root: Path, *, prefix: str = "") -> bytes:
    """Capture application-owned files deterministically; never scan repo evidence."""
    output = io.BytesIO()
    total = 0
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            total += len(data)
            if total > MAX_SNAPSHOT_BYTES:
                raise ValueError(
                    "This Cloudflare pilot has reached its 12 MiB working-data limit. "
                    "Export or migrate the cohort before adding more data. "
                    "The previous committed snapshot is preserved."
                )
            entry = ZipInfo(prefix + path.relative_to(root).as_posix())
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data)
    return output.getvalue()


def unpack_snapshot(data: bytes, root: Path) -> None:
    """Restore only bounded relative files into this host's private scratch space."""
    with ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if sum(item.file_size for item in entries) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Snapshot exceeds the Cloudflare pilot data limit.")
        names = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or entry.is_dir()
                or entry.filename in names
            ):
                raise ValueError("Snapshot contains an invalid file path.")
            names.add(entry.filename)
        # Only files in this adapter's scratch directory are replaced. Historical
        # R2 revisions and repository inputs are never removed or rewritten.
        for path in root.rglob("*") if root.exists() else []:
            if path.is_file() and path.relative_to(root).as_posix() not in names:
                path.unlink()
        root.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            path = root / entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(entry))


def merge_run(result: bytes, root: Path, job: dict) -> None:
    """Merge only this job's run artifacts, preserving concurrent drafts and history."""
    prefix = f"projects/{job['project_id']}/runs/{job['run_id']}/"
    with ZipFile(io.BytesIO(result)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Runner result exceeds the Cloudflare pilot data limit.")
        for entry in archive.infolist():
            if not entry.filename.startswith(prefix):
                raise ValueError(
                    "Runner result includes files outside the claimed run."
                )
            path = PurePosixPath(entry.filename)
            if ".." in path.parts or "\\" in entry.filename:
                raise ValueError("Runner result contains an invalid file path.")
            destination = root / entry.filename
            previous = destination.read_bytes() if destination.exists() else b""
            updated = archive.read(entry)
            if destination.name == "run_events.jsonl" and not updated.startswith(
                previous
            ):
                raise ValueError("Runner result would rewrite append-only run history.")
            if (
                destination.name
                not in {"status.json", "run_events.jsonl", "comparison.md"}
                and previous
                and updated != previous
            ):
                raise ValueError("Runner result changed an existing frozen artifact.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(updated)
