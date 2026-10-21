"""Offline Workers host contracts with real SQLite and immutable archive revisions."""

import asyncio
import importlib
import importlib.util
import io
import json
import sys
import types
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest

pytest.importorskip("flask")
pytest.importorskip("jwt")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
snapshots = importlib.import_module("extensions.cloudflare.snapshots")
build = importlib.import_module("extensions.cloudflare.build").build


def test_snapshot_store_restores_ownership_drafts_and_append_only_history(tmp_path):
    root = tmp_path / "scratch"
    store = snapshots.SnapshotStore(root)
    user = store.user("fictional-issuer", "fictional-subject", "owner@example.test")
    with store.connection(write=True) as db:
        db.execute(
            "INSERT INTO projects(id, owner_id, name, author) "
            "VALUES ('project', ?, 'test', 'test')",
            (user["id"],),
        )
        db.execute(
            "INSERT INTO drafts(project_id, exercise_id, version, data) "
            "VALUES ('project', 'frame_challenge', 1, ?)",
            (json.dumps({"framing": "FICTIONAL independent draft"}),),
        )
    ledger = root / "projects/project/ledger/events.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"fictional":"immutable provenance"}\n')
    archived = snapshots.pack_snapshot(root)
    assert snapshots.pack_snapshot(root) == archived
    ledger.write_text("damaged scratch copy")
    (root / "uncommitted.txt").write_text("not acknowledged")
    snapshots.unpack_snapshot(archived, root)
    assert ledger.read_text() == '{"fictional":"immutable provenance"}\n'
    assert not (root / "uncommitted.txt").exists()
    reopened = snapshots.SnapshotStore(root)
    with reopened.connection() as db:
        assert db.execute("SELECT owner_id FROM projects").fetchone()[0] == user["id"]
        assert db.execute("SELECT version FROM drafts").fetchone()[0] == 1
    with reopened.project_lock("project"):
        pass


@pytest.mark.parametrize(
    "name", ["../outside", "/outside", "folder/../../outside", "folder\\outside"]
)
def test_snapshot_rejects_unsafe_paths_before_replacing_scratch(name, tmp_path):
    archive = io.BytesIO()
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "FICTIONAL")
    root = tmp_path / "scratch"
    root.mkdir()
    existing = root / "existing"
    existing.write_text("preserved")
    with pytest.raises(ValueError, match="invalid file path"):
        snapshots.unpack_snapshot(archive.getvalue(), root)
    assert existing.read_text() == "preserved"


def test_run_merge_preserves_drafts_ledger_and_frozen_artifacts(tmp_path):
    root = tmp_path / "scratch"
    prefix = "projects/project/runs/run/"
    directory = root / prefix
    directory.mkdir(parents=True)
    (directory / "input_manifest.json").write_text("frozen")
    (directory / "run_events.jsonl").write_text("first\n")
    (root / "web.sqlite3").write_text("new independent draft metadata")
    archive = io.BytesIO()
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(prefix + "input_manifest.json", "frozen")
        bundle.writestr(prefix + "run_events.jsonl", "first\nsecond\n")
        bundle.writestr(prefix + "analyst_response.json", "FICTIONAL response")
    job = {"project_id": "project", "run_id": "run"}
    snapshots.merge_run(archive.getvalue(), root, job)
    assert (directory / "run_events.jsonl").read_text() == "first\nsecond\n"
    assert (root / "web.sqlite3").read_text() == "new independent draft metadata"
    for filename, content in (
        ("input_manifest.json", "changed"),
        ("run_events.jsonl", "replaced"),
    ):
        bad = io.BytesIO()
        with ZipFile(bad, "w") as bundle:
            bundle.writestr(prefix + filename, content)
        with pytest.raises(ValueError):
            snapshots.merge_run(bad.getvalue(), root, job)
    forbidden = io.BytesIO()
    with ZipFile(forbidden, "w") as bundle:
        bundle.writestr("projects/project/ledger/events.jsonl", "automatic approval")
    with pytest.raises(ValueError, match="outside the claimed run"):
        snapshots.merge_run(forbidden.getvalue(), root, job)


def test_build_contains_only_source_and_neutral_scaffold(tmp_path):
    destination = tmp_path / "bundle"
    build(destination)
    assert "Deployment scaffold" in (destination / "docs/brief.md").read_text()
    assert not (destination / "tests/workers/fixture.py").exists()
    assert not (destination / "extensions/web/.data").exists()
    assert (destination / "extensions/web/schema.sql").is_file()
    assert not any(
        path.name in {".git", "deployment.env", ".dev.vars"}
        for path in destination.rglob("*")
    )
    (destination / "unexpected.env").write_text("FICTIONAL private sentinel")
    with pytest.raises(ValueError, match="Unexpected files"):
        build(destination)


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    # Only the Cloudflare binding surface is replaced. Storage, snapshots, core,
    # quotas and job transitions run against real files/SQLite; native runtime
    # coverage lives in extensions/cloudflare/smoke.py.
    workers = types.ModuleType("workers")
    workers.DurableObject = type("DurableObject", (), {})
    workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})

    class Response:
        def __init__(self, body, *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers

    workers.Response = Response
    workers.wsgi = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "workers", workers)
    ffi = types.ModuleType("pyodide.ffi")
    ffi.create_once_callable = lambda callback: callback
    monkeypatch.setitem(sys.modules, "pyodide.ffi", ffi)
    spec = importlib.util.spec_from_file_location(
        "cloudflare_cohort_test", ROOT / "extensions/cloudflare/entry.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DATA_ROOT", tmp_path / "scratch")

    class Object:
        def __init__(self, data):
            self.data = data

        async def arrayBuffer(self):
            return self.data

    class Bucket:
        def __init__(self):
            self.objects = {}
            self.fail = False

        async def put(self, key, value):
            if self.fail:
                raise OSError("FICTIONAL R2 outage")
            if key in self.objects:
                assert self.objects[key] == value
            self.objects[key] = value

        async def get(self, key):
            return Object(self.objects[key]) if key in self.objects else None

    class Storage:
        def __init__(self):
            self.head = None
            self.alarm = None

        async def get(self, key):
            assert key == "head"
            return self.head

        async def put(self, key, value):
            assert key == "head"
            self.head = value

        async def getAlarm(self):
            return self.alarm

        async def setAlarm(self, value):
            self.alarm = value

    async def block_concurrency(callback):
        try:
            return await callback()
        except Exception:
            pytest.fail("The request escaped the gate and would reset the object.")

    instance = module.Cohort()
    instance.ctx = types.SimpleNamespace(
        storage=Storage(), blockConcurrencyWhile=block_concurrency
    )
    instance.env = types.SimpleNamespace(RESEARCH=Bucket())
    return instance, module.DATA_ROOT


@pytest.mark.parametrize(
    ("secret", "issuer", "message"),
    [
        ("", "https://fictional.cloudflareaccess.com", "WEB_SECRET_KEY"),
        ("fictional-secret", "fictional.cloudflareaccess.com", "https://TEAM"),
    ],
)
def test_configuration_errors_return_message_inside_gate(
    cohort, monkeypatch, secret, issuer, message
):
    instance, _root = cohort
    runtime = importlib.import_module("extensions.cloudflare.runtime")
    monkeypatch.setattr(
        runtime, "stage_resources", lambda: ROOT / "config/project.yaml"
    )
    instance.env.WEB_SECRET_KEY = secret
    instance.env.WEB_ACCESS_TEAM_DOMAIN = issuer
    instance.env.WEB_ACCESS_AUD = "fictional-audience"
    response = asyncio.run(instance.fetch(types.SimpleNamespace(method="GET")))
    assert response.status == 503
    assert message in response.body
    assert response.headers["Cache-Control"] == "no-store"
    assert instance.ctx.storage.head is None
    assert not instance.env.RESEARCH.objects


def test_request_r2_failure_returns_message_and_restores_committed_head(
    cohort, monkeypatch
):
    instance, root = cohort
    store = asyncio.run(instance.restore())
    previous = asyncio.run(instance.checkpoint(store))
    module = sys.modules[type(instance).__module__]
    monkeypatch.setattr(module, "hosted_app", lambda env: object())

    class Buffer:
        def to_py(self):
            return b"FICTIONAL response"

    async def wsgi_fetch(*args):
        (root / "uncommitted.txt").write_text("FICTIONAL unsaved change")
        return types.SimpleNamespace(arrayBuffer=array_buffer, status=200, headers=[])

    async def array_buffer():
        return Buffer()

    monkeypatch.setattr(module.wsgi, "fetch", wsgi_fetch, raising=False)
    instance.env.RESEARCH.fail = True
    response = asyncio.run(instance.fetch(types.SimpleNamespace(method="GET")))
    assert response.status == 503
    assert "previous saved snapshot is preserved" in response.body
    assert instance.ctx.storage.head == previous
    instance.env.RESEARCH.fail = False
    asyncio.run(instance.restore())
    assert not (root / "uncommitted.txt").exists()


def test_failed_r2_commit_keeps_previous_durable_head(cohort, monkeypatch):
    instance, root = cohort
    store = asyncio.run(instance.restore())
    previous = asyncio.run(instance.checkpoint(store))
    (root / "new.txt").write_text("FICTIONAL unsaved change")
    instance.env.RESEARCH.fail = True
    with pytest.raises(OSError, match="R2 outage"):
        asyncio.run(instance.checkpoint(store))
    assert instance.ctx.storage.head == previous
    instance.env.RESEARCH.fail = False
    asyncio.run(instance.restore())
    assert not (root / "new.txt").exists()
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOT_BYTES", 10)
    with pytest.raises(ValueError, match="working-data limit"):
        asyncio.run(instance.checkpoint(store))
    assert instance.ctx.storage.head == previous


def test_alarm_recovery_charges_interrupted_job_without_repeating_it(cohort):
    instance, root = cohort
    store = asyncio.run(instance.restore())
    owner = store.user("fictional", "subject", "tester@example.test")
    with store.connection(write=True) as db:
        db.execute(
            "INSERT INTO projects(id, owner_id, name, author) "
            "VALUES ('project', ?, 'test', 'test')",
            (owner["id"],),
        )
    job_id = store.enqueue(
        "project", "run", Decimal("0.10"), Decimal("0.50"), Decimal("1"), retry=False
    )
    asyncio.run(instance.checkpoint(store))
    claimed = asyncio.run(instance.claim())
    assert claimed["job"]["id"] == job_id
    assert instance.ctx.storage.alarm is not None
    assert asyncio.run(instance.claim()) is None
    reopened = snapshots.SnapshotStore(root)
    with reopened.connection() as db:
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == "interrupted"
        assert db.execute("SELECT charged FROM spending").fetchone()[0] == 100_000
    # A late result cannot replace an interruption or release its conservative charge.
    asyncio.run(instance.finish(claimed, {"artifact": "must-not-be-read"}))
    with reopened.connection() as db:
        assert db.execute("SELECT charged FROM spending").fetchone()[0] == 100_000


def test_production_configs_disable_public_runner_and_live_calls():
    import tomllib

    configs = ROOT / "extensions/cloudflare"
    web = tomllib.loads((configs / "wrangler.toml").read_text())
    runner = tomllib.loads((configs / "wrangler.runner.toml").read_text())
    from extensions.web.identity import AccessIdentity

    AccessIdentity(web["vars"]["WEB_ACCESS_TEAM_DOMAIN"], web["vars"]["WEB_ACCESS_AUD"])
    assert not runner["workers_dev"]
    for config in (web, runner):
        assert not config["preview_urls"]
        assert config["vars"]["WEB_LIVE_ENABLED"] == "0"
        assert "OPENAI_API_KEY" not in config["vars"]
        assert "DEV_MODE" not in config["vars"]
    assert "routes" not in runner
    assert web["services"][0]["service"] == runner["name"]
