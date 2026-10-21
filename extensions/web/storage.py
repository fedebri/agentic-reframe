"""Web identity, drafts, and durable job reservations; core artifacts stay in files."""

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from uuid import uuid4


def budget_units(amount: Decimal) -> int:
    """Round estimated USD up to integer microdollars for atomic quota accounting."""
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def reserved(directory: Path) -> Decimal:
    """Read accepted core reservations, including failed and uncertain attempts."""
    return sum(
        (
            Decimal(event["details"]["reserved_usd"])
            for line in (directory / "run_events.jsonl").read_text().splitlines()
            if (event := json.loads(line))["event_type"] == "budget_checked"
            and event["details"].get("reservation_accepted")
        ),
        Decimal("0"),
    )


class WebStore:
    """One local SQLite database shared by the web process and a single worker."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "web.sqlite3"
        # WAL initialization needs exclusive access on the first cold start.
        # This lock is used only at startup, never around HTTP requests or AI calls.
        with (root / ".metadata-lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(Path(__file__).with_name("schema.sql").read_text())

    @contextmanager
    def connection(self, *, write: bool = False):
        """Commit short transactions; never hold one open during a model call."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    @contextmanager
    def project_lock(self, project_id: str, *, shared: bool = False):
        """Serialize filesystem operations within an already-authorized project."""
        path = self.root / "projects" / project_id / ".web-lock"
        with path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            yield

    def user(self, issuer: str, subject: str, email: str | None) -> dict:
        """Resolve a verified external subject or a signed local browser identity."""
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO users(id, issuer, subject, email) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(issuer, subject) DO UPDATE SET email=excluded.email",
                (uuid4().hex, issuer, subject, email),
            )
            return dict(
                db.execute(
                    "SELECT * FROM users WHERE issuer=? AND subject=?",
                    (issuer, subject),
                ).fetchone()
            )

    def claim_legacy(self, owner_id: str, project_ids: list[str]) -> None:
        """Bind only the projects proven by an existing signed cookie."""
        with self.connection(write=True) as db:
            for project_id in project_ids:
                existing = db.execute(
                    "SELECT owner_id FROM projects WHERE id=?", (project_id,)
                ).fetchone()
                if existing is not None:
                    continue
                directory = self.root / "projects" / project_id
                metadata = json.loads((directory / "project.json").read_text())
                db.execute(
                    "INSERT INTO projects(id, owner_id, name, author) VALUES (?, ?,"
                    " ?, ?)",
                    (project_id, owner_id, metadata["name"], metadata["author"]),
                )
                for run_id in metadata["runs"]:
                    db.execute(
                        "INSERT INTO spending(project_id, run_id, charged) VALUES "
                        "(?, ?, ?)",
                        (
                            project_id,
                            run_id,
                            budget_units(reserved(directory / "runs" / run_id)),
                        ),
                    )

    def available(
        self,
        db: sqlite3.Connection,
        project_id: str,
        run_id: str,
        run_cap: Decimal,
        user_cap: Decimal,
        total_cap: Decimal,
    ) -> int:
        """Calculate unallocated funds using the caller's current SQLite transaction."""
        owner_id = db.execute(
            "SELECT owner_id FROM projects WHERE id=?", (project_id,)
        ).fetchone()["owner_id"]
        charges = db.execute(
            "SELECT p.owner_id, s.project_id, s.run_id, s.charged "
            "FROM spending s JOIN projects p ON p.id=s.project_id"
        ).fetchall()
        pending = db.execute(
            "SELECT p.owner_id, j.allocated FROM jobs j JOIN projects p ON "
            "p.id=j.project_id "
            "WHERE j.state IN ('queued', 'running')"
        ).fetchall()
        used = sum(row["charged"] for row in charges) + sum(
            row["allocated"] for row in pending
        )
        user_used = sum(
            row["charged"] for row in charges if row["owner_id"] == owner_id
        )
        user_used += sum(
            row["allocated"] for row in pending if row["owner_id"] == owner_id
        )
        run_used = next(
            (
                row["charged"]
                for row in charges
                if row["project_id"] == project_id and row["run_id"] == run_id
            ),
            0,
        )
        return min(
            budget_units(run_cap) - run_used,
            budget_units(user_cap) - user_used,
            budget_units(total_cap) - used,
        )

    def enqueue(
        self,
        project_id: str,
        run_id: str,
        run_cap: Decimal,
        user_cap: Decimal,
        total_cap: Decimal,
        *,
        retry: bool,
    ) -> str:
        """Reserve all quota atomically before a job can make any provider request."""
        with self.connection(write=True) as db:
            active = db.execute(
                "SELECT id, run_id FROM jobs WHERE project_id=? "
                "AND state IN ('queued', 'running')",
                (project_id,),
            ).fetchone()
            if active:
                if active["run_id"] == run_id:
                    return active["id"]
                raise ValueError(
                    "Another analysis is queued or running in this project."
                )
            db.execute(
                "INSERT OR IGNORE INTO spending(project_id, run_id) VALUES (?, ?)",
                (project_id, run_id),
            )
            allocation = self.available(
                db, project_id, run_id, run_cap, user_cap, total_cap
            )
            if allocation <= 0:
                raise ValueError(
                    "The run, tester, or deployment spending allowance is exhausted."
                )
            job_id = uuid4().hex
            db.execute(
                "INSERT INTO jobs(id, project_id, run_id, state, allocated, retry) "
                "VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, project_id, run_id, allocation, int(retry)),
            )
            return job_id

    def claim_job(self) -> dict | None:
        """Claim the oldest job; the worker also holds a singleton process lock."""
        with self.connection(write=True) as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created_at, rowid"
                " LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET state='running', "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id=?",
                (row["id"],),
            )
            return dict(row)

    def finish_job(self, job: dict, additional: int, error: str | None = None) -> None:
        """Retain accepted/uncertain charges and release only unused allocated funds."""
        with self.connection(write=True) as db:
            db.execute(
                "UPDATE spending SET charged=charged+? WHERE project_id=? AND run_id=?",
                (additional, job["project_id"], job["run_id"]),
            )
            db.execute(
                "UPDATE jobs SET state=?, error=?, allocated=0, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id=?",
                ("failed" if error else "succeeded", error, job["id"]),
            )
            db.execute(
                "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', "
                "'now') WHERE id=?",
                (job["project_id"],),
            )

    def interrupt_running(self) -> None:
        """After acquiring the worker lock, retain interrupted allocations."""
        with self.connection(write=True) as db:
            for job in db.execute(
                "SELECT * FROM jobs WHERE state='running'"
            ).fetchall():
                db.execute(
                    "UPDATE spending SET charged=charged+? WHERE project_id=? AND "
                    "run_id=?",
                    (job["allocated"], job["project_id"], job["run_id"]),
                )
            db.execute(
                "UPDATE jobs SET state='interrupted', allocated=0, "
                "error='The worker stopped. The allocation remains charged; "
                "explicit retry is required.', "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE state='running'"
            )
