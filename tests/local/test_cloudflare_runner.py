"""Offline runner dispatch/recovery; the native fixture tests the full workflow."""

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("jwt")


@pytest.fixture
def runner(monkeypatch):
    workers = types.ModuleType("workers")

    class Entrypoint:
        def __init__(self, ctx=None, env=None):
            self.ctx = ctx
            self.env = env

    class Response:
        def __init__(self, body, *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers or {"Content-Type": "application/json"}

        async def text(self):
            return self.body

    class Storage:
        def __init__(self):
            self.values = {}

        async def get(self, key):
            await asyncio.sleep(0)
            return self.values.get(key)

        async def put(self, key, value):
            await asyncio.sleep(0)
            self.values[key] = value

    class Request:
        method = "POST"
        url = "https://runner.internal/execute"

        def __init__(self, job_id="fictional-job"):
            self.payload = {"job_id": job_id, "snapshot": "fictional.zip"}

        def clone(self):
            return self

        async def json(self):
            return self.payload

    calls = []

    async def execute(app, request, env):
        calls.append(request.payload["job_id"])
        await asyncio.sleep(0)
        return Response(
            json.dumps({"artifact": "fictional-result.zip", "charged": 12}),
            headers=[("Content-Type", "application/json")],
        )

    workers.DurableObject = workers.WorkerEntrypoint = Entrypoint
    workers.Response = Response
    workers.wsgi = types.SimpleNamespace(fetch=execute)
    monkeypatch.setitem(sys.modules, "workers", workers)
    path = Path(__file__).resolve().parents[2] / "extensions/cloudflare/runner.py"
    spec = importlib.util.spec_from_file_location("cloudflare_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, types.SimpleNamespace(storage=Storage()), Request, calls


def test_regular_worker_only_forwards_to_the_analysis_object(runner):
    module, _, Request, calls = runner
    forwarded = []
    expected = module.WorkerResponse("fictional reply")

    class Namespace:
        def idFromName(self, name):
            assert name == "analysis-v1"
            return "fictional-object-id"

        def get(self, object_id):
            assert object_id == "fictional-object-id"
            return self

        async def fetch(self, request):
            forwarded.append(request)
            return expected

    gateway = module.Default(env=types.SimpleNamespace(ANALYSIS=Namespace()))
    request = Request()
    assert asyncio.run(gateway.fetch(request)) is expected
    assert forwarded == [request]
    assert calls == []


def test_concurrent_duplicate_requests_and_restart_reuse_the_saved_result(runner):
    module, ctx, Request, calls = runner

    async def exercise():
        actor = module.AnalysisRunner(ctx, types.SimpleNamespace())
        first, duplicate = await asyncio.gather(
            actor.fetch(Request()), actor.fetch(Request())
        )
        restarted = module.AnalysisRunner(ctx, types.SimpleNamespace())
        recovered = await restarted.fetch(Request())
        assert first.status == duplicate.status == recovered.status == 200
        assert first.body == duplicate.body == recovered.body

    asyncio.run(exercise())
    assert calls == ["fictional-job"]
    assert json.loads(ctx.storage.values["job:fictional-job"])["charged"] == 12


@pytest.mark.parametrize("failure", ["exception", "http"])
def test_interrupted_dispatch_cannot_repeat_but_new_retry_job_can_run(
    runner, monkeypatch, failure
):
    module, ctx, Request, calls = runner
    original = module.wsgi.fetch

    async def interrupted(*args):
        if failure == "exception":
            raise RuntimeError("FICTIONAL interrupted execution")
        return module.WorkerResponse("FICTIONAL HTTP failure", status=500)

    monkeypatch.setattr(module.wsgi, "fetch", interrupted)

    async def exercise():
        actor = module.AnalysisRunner(ctx, types.SimpleNamespace())
        if failure == "exception":
            with pytest.raises(RuntimeError, match="FICTIONAL interrupted"):
                await actor.fetch(Request())
        else:
            assert (await actor.fetch(Request())).status == 500
        assert ctx.storage.values["job:fictional-job"] == "started"
        monkeypatch.setattr(module.wsgi, "fetch", original)
        restarted = module.AnalysisRunner(ctx, types.SimpleNamespace())
        blocked = await restarted.fetch(Request())
        assert blocked.status == 409
        assert "Authorize a new retry" in blocked.body
        assert (
            await restarted.fetch(Request("fictional-authorized-retry"))
        ).status == 200

    asyncio.run(exercise())
    assert calls == ["fictional-authorized-retry"]


@pytest.mark.parametrize("stage", ["dispatch", "result"])
def test_storage_failure_cannot_acknowledge_or_repeat_execution(
    runner, monkeypatch, stage
):
    module, ctx, Request, calls = runner
    original = ctx.storage.put

    async def fail_write(key, value):
        if (value == "started") == (stage == "dispatch"):
            raise OSError("FICTIONAL storage failure")
        await original(key, value)

    monkeypatch.setattr(ctx.storage, "put", fail_write)

    async def exercise():
        actor = module.AnalysisRunner(ctx, types.SimpleNamespace())
        with pytest.raises(OSError, match="FICTIONAL storage"):
            await actor.fetch(Request())
        if stage == "result":
            assert ctx.storage.values["job:fictional-job"] == "started"
            assert (await actor.fetch(Request())).status == 409
        else:
            assert not ctx.storage.values

    asyncio.run(exercise())
    assert calls == (["fictional-job"] if stage == "result" else [])
