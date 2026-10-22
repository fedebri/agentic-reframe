"""Private forwarder and Durable Object for authorized research analysis."""

import asyncio
import hashlib
import json
import logging
from urllib.parse import urlsplit

from flask import Flask, Response, abort, request
from workers import DurableObject, WorkerEntrypoint, wsgi
from workers import Response as WorkerResponse

from agentic_dt.schemas import RunManifest
from extensions.cloudflare.runtime import DATA_ROOT, api_client, stage_resources
from extensions.cloudflare.snapshots import (
    SnapshotStore,
    pack_snapshot,
    unpack_snapshot,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app.post("/execute")
def execute():
    """Execute exactly the job claimed in an immutable coordinator snapshot."""
    from pyodide.ffi import run_sync

    env = request.environ["workers.env"]
    key = getattr(env, "OPENAI_API_KEY", "")
    payload = request.get_json()
    logger.info("Runner job %s: restoring snapshot", payload["job_id"])
    archive = run_sync(env.RESEARCH.get(payload["snapshot"]))
    if archive is None:
        abort(409, "The claimed snapshot is unavailable.")
    unpack_snapshot(bytes(run_sync(archive.arrayBuffer())), DATA_ROOT)
    stage_resources()
    store = SnapshotStore(DATA_ROOT)
    with store.connection() as db:
        row = db.execute(
            "SELECT * FROM jobs WHERE id=? AND state='running'", (payload["job_id"],)
        ).fetchone()
        if row is None:
            abort(409, "This snapshot does not contain the claimed running job.")
        job = dict(row)
        before = db.execute(
            "SELECT charged FROM spending WHERE project_id=? AND run_id=?",
            (job["project_id"], job["run_id"]),
        ).fetchone()["charged"]
    if getattr(env, "WEB_LIVE_ENABLED", "0") != "1":
        store.finish_job(job, 0, "Live AI calls are disabled in the private runner.")
    elif not key:
        store.finish_job(job, 0, "Set OPENAI_API_KEY on the private runner.")
    else:
        logger.info("Runner job %s: loading analysis runtime", job["id"])
        from extensions.web.worker import work_once

        logger.info("Runner job %s: initializing API client", job["id"])
        manifest = RunManifest.model_validate_json(
            DATA_ROOT.joinpath(
                "projects",
                job["project_id"],
                "runs",
                job["run_id"],
                "input_manifest.json",
            ).read_bytes()
        )
        with api_client(key, manifest.model.timeout_seconds) as client:
            logger.info("Runner job %s: executing analysis", job["id"])
            work_once(store, job=job, client=client)
    with store.connection() as db:
        finished = dict(
            db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        )
        charged = (
            db.execute(
                "SELECT charged FROM spending WHERE project_id=? AND run_id=?",
                (job["project_id"], job["run_id"]),
            ).fetchone()["charged"]
            - before
        )
    prefix = f"projects/{job['project_id']}/runs/{job['run_id']}/"
    logger.info("Runner job %s: saving result (%s)", job["id"], finished["state"])
    result = pack_snapshot(DATA_ROOT / prefix, prefix=prefix)
    artifact = f"results/{job['id']}/{hashlib.sha256(result).hexdigest()}.zip"
    run_sync(env.RESEARCH.put(artifact, result))
    logger.info("Runner job %s: result saved", job["id"])
    return Response(
        json.dumps(
            {"artifact": artifact, "charged": charged, "error": finished["error"]}
        ),
        mimetype="application/json",
    )


class AnalysisRunner(DurableObject):
    """Run the Python workflow under the Durable Object CPU allowance."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        # Serialize scratch-file use without blockConcurrencyWhile's wall timeout.
        self._lock = asyncio.Lock()

    async def fetch(self, request):
        """Persist dispatch before execution; never repeat an uncertain job."""
        async with self._lock:
            if request.method != "POST" or urlsplit(request.url).path != "/execute":
                return await wsgi.fetch(app, request, self.env)
            payload = await request.clone().json()
            key = f"job:{payload['job_id']}"
            previous = await self.ctx.storage.get(key)
            if previous == "started":
                return WorkerResponse(
                    "This job was already dispatched without a confirmed result. "
                    "Authorize a new retry from the saved run page.",
                    status=409,
                )
            if previous is not None:
                return WorkerResponse(
                    previous, headers={"Content-Type": "application/json"}
                )
            await self.ctx.storage.put(key, "started")
            logging.basicConfig(level=logging.INFO)
            logger.info(
                "AnalysisRunner job %s: executing in Durable Object", payload["job_id"]
            )
            response = await wsgi.fetch(app, request, self.env)
            # Finish WSGI iterators while this request owns the scratch files.
            body = await response.text()
            if response.status == 200:
                await self.ctx.storage.put(key, body)
            return WorkerResponse(
                body, status=response.status, headers=list(response.headers)
            )


class Default(WorkerEntrypoint):
    """Keep the regular Worker limited to forwarding private service requests."""

    async def fetch(self, request):
        runner_id = self.env.ANALYSIS.idFromName("analysis-v1")
        return await self.env.ANALYSIS.get(runner_id).fetch(request)
