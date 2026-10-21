"""Run authorized web jobs outside HTTP requests, without modifying the core runtime."""

import fcntl
import logging
import signal
from decimal import Decimal
from pathlib import Path
from threading import Event

from openai import APIError

from agentic_dt.schemas import RunManifest
from agentic_dt.workflow import run_exercise

from .storage import WebStore, budget_units, reserved

logger = logging.getLogger(__name__)


def public_error(error: Exception) -> str:
    """Keep SDK request bodies and credentials out of web errors and worker logs."""
    if isinstance(error, APIError):
        return (
            f"AI service error ({type(error).__name__}, "
            f"HTTP {getattr(error, 'status_code', 'unavailable')}, "
            f"request {getattr(error, 'request_id', 'unavailable')}). "
            "Review the saved run before explicitly retrying."
        )
    if isinstance(error, ValueError):
        return str(error)[:2000]
    return (
        f"Analysis stopped ({type(error).__name__}). "
        "Review the saved run before retrying."
    )


def work_once(store: WebStore) -> bool:
    """Execute one queued job; callers must hold the worker's singleton file lock."""
    job = store.claim_job()
    if job is None:
        return False
    project = store.root / "projects" / job["project_id"]
    directory = project / "runs" / job["run_id"]
    before = Decimal("0")
    started = False
    error = None
    try:
        # Finish a short in-flight filesystem operation before model execution.
        # The active DB job blocks subsequent mutations; reads/draft saves continue.
        with store.project_lock(job["project_id"]):
            manifest = RunManifest.model_validate_json(
                (directory / "input_manifest.json").read_bytes()
            )
            before = reserved(directory)
        started = True
        run_exercise(
            project / "config/project.yaml",
            manifest.exercise_id,
            directory,
            [Path(path) for path in manifest.selected_evidence_paths],
            manifest.critic_enabled,
            True,
            before + Decimal(job["allocated"]) / 1_000_000,
            retry_failed=bool(job["retry"]),
            context_claim_ids=[claim.claim_id for claim in manifest.approved_context],
            human_frame_path=Path(manifest.human_frame.source_path),
        )
    except Exception as failure:
        # A failed job must be settled and visible, not crash the durable worker loop.
        error = public_error(failure)
        logger.error("Job %s failed (%s)", job["id"], type(failure).__name__)
    try:
        additional = budget_units(reserved(directory) - before) if started else 0
    except (OSError, ValueError):
        additional = job["allocated"]
        error = (
            "Could not verify the run log. The full allocation remains charged; "
            "inspect this run before retrying."
        )
    store.finish_job(job, additional, error)
    return True


def main() -> None:
    """Start one durable worker; interrupted jobs require fresh human authorization."""
    from .app import create_app

    logging.basicConfig(level=logging.INFO)
    store = create_app().extensions["web_store"]
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    with (store.root / ".worker-lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("A worker already owns this WEB_DATA_ROOT.") from error
        store.interrupt_running()
        logger.info("Worker ready; waiting for explicitly authorized jobs")
        while not stopping.is_set():
            if not work_once(store):
                stopping.wait(1)


if __name__ == "__main__":
    main()
