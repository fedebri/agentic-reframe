"""Public Worker and singleton Durable Object for a small private testing cohort."""

import hashlib
import io
import json
import logging
import time
from urllib.parse import urlsplit
from zipfile import ZipFile

from workers import DurableObject, Response, WorkerEntrypoint, wsgi

from extensions.cloudflare.runtime import DATA_ROOT, hosted_app
from extensions.cloudflare.snapshots import (
    SnapshotStore,
    merge_run,
    pack_snapshot,
    unpack_snapshot,
)

logger = logging.getLogger(__name__)


class Cohort(DurableObject):
    """Commit one consistent metadata/files snapshot; never hold the gate during AI."""

    async def gate(self, action, *args):
        """Serialize short application operations across asynchronous storage calls."""
        from pyodide.ffi import create_once_callable

        async def run():
            return await action(*args)

        return await self.ctx.blockConcurrencyWhile(create_once_callable(run))

    async def restore(self):
        """Always restore the committed head, including after an aborted request."""
        head = await self.ctx.storage.get("head")
        if head:
            archive = await self.env.RESEARCH.get(head)
            if archive is None:
                raise ValueError("The committed research snapshot is unavailable.")
            data = bytes(await archive.arrayBuffer())
        else:
            output = io.BytesIO()
            with ZipFile(output, "w"):
                pass
            data = output.getvalue()
        unpack_snapshot(data, DATA_ROOT)
        return SnapshotStore(DATA_ROOT)

    async def checkpoint(self, store):
        """Upload an immutable revision before atomically advancing the durable head."""
        data = pack_snapshot(DATA_ROOT)
        head = f"snapshots/{hashlib.sha256(data).hexdigest()}.zip"
        previous = await self.ctx.storage.get("head")
        if head != previous:
            await self.env.RESEARCH.put(head, data)
        with store.connection() as db:
            states = {
                row[0]
                for row in db.execute(
                    "SELECT state FROM jobs WHERE state IN ('queued', 'running')"
                )
            }
        alarm = await self.ctx.storage.getAlarm()
        if "running" in states:
            if alarm is None:
                await self.ctx.storage.setAlarm(int(time.time() * 1000) + 600_000)
        elif "queued" in states:
            await self.ctx.storage.setAlarm(int(time.time() * 1000) + 1000)
        # The alarm is installed first: a failure cannot acknowledge a durable job
        # that has no wake-up. Old R2 revisions remain available for recovery/export.
        await self.ctx.storage.put("head", head)
        return head

    async def serve(self, request):
        store = await self.restore()
        app = hosted_app(self.env)
        response = await wsgi.fetch(app, request, self.env)
        # Finish WSGI file iterators before another operation restores scratch files.
        body = bytes((await response.arrayBuffer()).to_py())
        await self.checkpoint(store)
        return Response(
            body
            if request.method != "HEAD" and response.status not in {204, 304}
            else None,
            status=response.status,
            headers=list(response.headers),
        )

    async def fetch(self, request):
        try:
            return await self.gate(self.serve, request)
        except ValueError as error:
            return Response(
                str(error), status=503, headers={"Cache-Control": "no-store"}
            )
        except Exception as error:
            logger.error("Research request interrupted (%s)", type(error).__name__)
            return Response(
                "The request could not be committed. Reload the page before "
                "trying again. "
                "The previous saved snapshot is preserved.",
                status=503,
                headers={"Cache-Control": "no-store"},
            )

    async def claim(self):
        store = await self.restore()
        with store.connection() as db:
            running = db.execute("SELECT id FROM jobs WHERE state='running'").fetchone()
        if running:
            # Alarm retries or a new isolate must not repeat an uncertain paid call.
            store.interrupt_running()
            await self.checkpoint(store)
            return None
        job = store.claim_job()
        if job is None:
            return None
        await self.ctx.storage.setAlarm(int(time.time() * 1000) + 600_000)
        head = await self.checkpoint(store)
        return {"job": job, "snapshot": head}

    async def finish(self, claimed, result):
        store = await self.restore()
        job = claimed["job"]
        with store.connection() as db:
            current = db.execute(
                "SELECT state FROM jobs WHERE id=?", (job["id"],)
            ).fetchone()
        if current is None or current["state"] != "running":
            return
        if result is None:
            # A runner/network failure can happen after the provider has charged us.
            # Retain the whole allocation, preserving the explicit retry policy.
            store.interrupt_running()
        else:
            artifact = await self.env.RESEARCH.get(result["artifact"])
            if artifact is None:
                raise ValueError(
                    "Runner result is unavailable; do not automatically retry."
                )
            merge_run(bytes(await artifact.arrayBuffer()), DATA_ROOT, job)
            store.finish_job(job, result["charged"], result["error"])
        await self.checkpoint(store)

    async def alarm(self, *_args):
        claimed = await self.gate(self.claim)
        if claimed is None:
            return
        result = None
        try:
            # This await is outside the gate: browser reads and draft saves continue.
            response = await self.env.RUNNER.fetch(
                "https://runner.internal/execute",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps(
                    {"snapshot": claimed["snapshot"], "job_id": claimed["job"]["id"]}
                ),
            )
            if response.status == 200:
                result = await response.json()
        except Exception as error:
            logger.error("Analysis runner interrupted (%s)", type(error).__name__)
        await self.gate(self.finish, claimed, result)


class Default(WorkerEntrypoint):
    """Send all authenticated application traffic to one private cohort coordinator."""

    async def fetch(self, request):
        url = urlsplit(request.url)
        if url.path == "/health":
            return Response.json({"status": "ok"})
        local = getattr(self.env, "DEV_MODE", "0") == "1"
        if local and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return Response(
                "Local development mode is restricted to loopback URLs.", status=503
            )
        if not local and not request.headers.get("Cf-Access-Jwt-Assertion"):
            return Response(
                "Sign in through the configured Cloudflare Access hostname.", status=401
            )
        cohort_id = self.env.COHORT.idFromName("cohort-v1")
        return await self.env.COHORT.get(cohort_id).fetch(request)
