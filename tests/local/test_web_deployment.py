"""Offline deployment checks with real JWT signatures and fictional projects."""

import base64
import importlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("flask")
jwt = pytest.importorskip("jwt", reason="Install extensions/web/requirements.txt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
web = importlib.import_module("extensions.web.app")
worker = importlib.import_module("extensions.web.worker")
storage = importlib.import_module("extensions.web.storage")


def submit(client, path, data=None):
    """Submit the actual CSRF and active-project fields issued to this browser."""
    with client.session_transaction() as session:
        fields = {
            "csrf": session["csrf"],
            "project_id": session.get("workspace_id", ""),
        }
    return client.post(path, data={**fields, **(data or {})})


@pytest.fixture
def hosted(project, tmp_path, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    monkeypatch.setattr(
        jwt.PyJWKClient,
        "fetch_data",
        lambda _self: {
            "keys": [{**jwk, "kid": "fictional-key", "use": "sig", "alg": "RS256"}]
        },
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = web.create_app(
        {
            "TESTING": True,
            "PROJECT_CONFIG": project,
            "DATA_ROOT": tmp_path / "hosted",
            "SECRET_KEY": "fictional-hosted-cookie-key",
            "ACCESS_PASSWORD": "",
            "AUTH_MODE": "cloudflare",
            "ACCESS_TEAM_DOMAIN": "https://fictional.cloudflareaccess.com",
            "ACCESS_AUD": "fictional-audience",
            "ADMIN_EMAILS": "admin@example.test",
            "RUN_BUDGET_USD": "0.01",
            "USER_BUDGET_USD": "0.05",
            "TOTAL_BUDGET_USD": "0.10",
            "LIVE_ENABLED": True,
        }
    )

    def token(email="tester@example.test", **changes):
        payload = {
            "sub": f"fictional-{email}",
            "email": email,
            "iss": "https://fictional.cloudflareaccess.com",
            "aud": ["fictional-audience"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        payload.update(changes)
        return jwt.encode(
            payload, private, algorithm="RS256", headers={"kid": "fictional-key"}
        )

    return app, token


@pytest.fixture
def actor(hosted):
    app, token = hosted

    def client_for(email="tester@example.test"):
        client = app.test_client()
        client.environ_base["HTTP_CF_ACCESS_JWT_ASSERTION"] = token(email)
        assert client.get("/").status_code == 200
        return client

    return client_for


@pytest.fixture
def owner(actor):
    client = actor()
    assert (
        submit(
            client,
            "/create",
            {
                "name": "FICTIONAL private project",
                "author": "fictional-participant",
                "brief_text": "FICTIONAL workshop access brief.",
            },
        ).status_code
        == 302
    )
    return client


@pytest.fixture
def answers():
    return {
        "exercise": "frame_challenge",
        "framing": "FICTIONAL-PRIVATE-HUMAN-DRAFT",
        "observations": "A fictional brief mentions access.",
        "assumptions": "The fictional cause is unknown.",
        "alternative_frame": "Investigate timing instead.",
        "open_questions": "Which fictional roles are missing?",
    }


@pytest.fixture
def pending(owner, answers, hosted):
    response = submit(owner, "/project/prepare", answers)
    assert response.status_code == 302
    with owner.session_transaction() as session:
        project_id = session["workspace_id"]
    store = hosted[0].extensions["web_store"]
    directory = (
        store.root
        / "projects"
        / project_id
        / "runs"
        / response.headers["Location"].rsplit("/", 1)[1]
    )
    return response.headers["Location"], directory, project_id


@pytest.fixture
def fake_sdk(pending, fake_client_type, monkeypatch):
    _, directory, _ = pending
    manifest = web.RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_text()
    )
    client = fake_client_type(
        [
            {
                "role": "analyst",
                "exercise_id": manifest.exercise_id,
                "claims": [
                    {
                        "local_id": f"c{i}",
                        "statement": f"FICTIONAL {deliverable}: workshop access.",
                        "claim_type": "observation",
                        "deliverable": deliverable,
                        "evidence_refs": [manifest.sources[0].source_id],
                        "citations": [
                            {
                                "source_id": manifest.sources[0].source_id,
                                "passage_id": "p1",
                            }
                        ],
                        "derived_from": [],
                        "confidence": 0.8,
                        "public_reasoning_summary": "The brief names this topic.",
                        "open_questions": ["Which fictional roles are missing?"],
                    }
                    for i, deliverable in enumerate(manifest.deliverables)
                ],
            }
        ]
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fictional-never-sent-sdk-key")
    monkeypatch.setattr(
        importlib.import_module("agentic_dt.workflow"),
        "OpenAI",
        lambda **_kwargs: nullcontext(client),
    )
    return client


def test_cloudflare_rejects_forged_email_headers_and_missing_tokens(hosted):
    app, _ = hosted
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert (
        client.get(
            "/", headers={"Cf-Access-Authenticated-User-Email": "admin@example.test"}
        ).status_code
        == 401
    )
    assert client.get("/admin").status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"aud": ["wrong-audience"]},
        {"iss": "https://wrong.cloudflareaccess.com"},
        {"sub": ""},
        {"email": ""},
        {"email": 123},
        {"nbf": 9999999999},
    ],
)
def test_cloudflare_validates_signed_claims(hosted, changes):
    app, token = hosted
    assert (
        app.test_client()
        .get("/", headers={"Cf-Access-Jwt-Assertion": token(**changes)})
        .status_code
        == 401
    )


def test_cloudflare_rejects_tampering_and_wrong_algorithm(hosted):
    app, token = hosted
    encoded = token().split(".")
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps({"email": "admin@example.test"}).encode())
        .rstrip(b"=")
        .decode()
    )
    assert (
        app.test_client()
        .get(
            "/",
            headers={
                "Cf-Access-Jwt-Assertion": f"{encoded[0]}.{forged_payload}.{encoded[2]}"
            },
        )
        .status_code
        == 401
    )
    wrong = jwt.encode(
        {"sub": "attacker", "email": "admin@example.test"},
        "fictional-secret-only-for-negative-test",
        algorithm="HS256",
        headers={"kid": "fictional-key"},
    )
    assert (
        app.test_client()
        .get("/", headers={"Cf-Access-Jwt-Assertion": wrong})
        .status_code
        == 401
    )


def test_same_identity_resumes_projects_on_another_machine(owner, actor, pending):
    _, _, project_id = pending
    another = actor()
    assert b"FICTIONAL private project" in another.get("/projects").data
    assert submit(another, "/projects", {"workspace_id": project_id}).status_code == 302
    assert b"FICTIONAL workshop access brief." in another.get("/project").data
    response = another.get("/")
    assert "Secure;" in response.headers["Set-Cookie"]


def test_other_identity_cannot_read_project_or_run(owner, actor, pending, hosted):
    run_url, _, project_id = pending
    other = actor("other@example.test")
    assert b"FICTIONAL private project" not in other.get("/projects").data
    assert submit(other, "/projects", {"workspace_id": project_id}).status_code == 404
    with other.session_transaction() as session:
        session["workspace_id"] = project_id
    assert other.get("/project").status_code == 404
    assert other.get(run_url).status_code == 404
    assert other.get(f"/admin/projects/{project_id}").status_code == 403
    assert other.get("/admin").status_code == 403


def test_drafts_survive_new_browser_and_detect_conflicting_saves(
    owner, actor, answers, hosted
):
    assert b"Draft saved." not in owner.get("/project?saved=1").data
    partial = {
        "exercise": "frame_challenge",
        "framing": "FICTIONAL unfinished <script>draft</script>",
        "draft_version": "0",
    }
    assert submit(owner, "/project/draft", partial).status_code == 302
    with owner.session_transaction() as session:
        project_id = session["workspace_id"]
    second = actor()
    assert submit(second, "/projects", {"workspace_id": project_id}).status_code == 302
    assert (
        b"FICTIONAL unfinished &lt;script&gt;draft&lt;/script&gt;"
        in second.get("/project").data
    )
    assert (
        submit(
            second,
            "/project/draft",
            {**partial, "framing": "FICTIONAL second machine", "draft_version": "1"},
        ).status_code
        == 302
    )
    stale = submit(
        owner,
        "/project/draft",
        {**partial, "framing": "FICTIONAL stale edit", "draft_version": "1"},
    )
    assert stale.status_code == 409
    assert b"FICTIONAL stale edit" in stale.data
    assert b"FICTIONAL second machine" in owner.get("/project").data
    directory = hosted[0].extensions["web_store"].root / "projects" / project_id
    assert not (directory / "ledger/events.jsonl").exists()
    assert json.loads((directory / "project.json").read_text())["runs"] == {}


def test_stale_project_form_cannot_write_to_a_different_project(owner, actor):
    with owner.session_transaction() as session:
        old = session["workspace_id"]
    assert (
        submit(
            owner,
            "/create",
            {
                "restart_from": old,
                "name": "FICTIONAL restart",
                "author": "fictional",
                "brief_text": "FICTIONAL revised brief.",
            },
        ).status_code
        == 302
    )
    assert (
        submit(
            owner,
            "/project/draft",
            {"project_id": old, "exercise": "frame_challenge", "framing": "stale"},
        ).status_code
        == 409
    )


def test_admin_can_publish_a_brief_for_independent_copies(
    owner, actor, pending, hosted
):
    _, _, project_id = pending
    admin = actor("admin@example.test")
    assert b"FICTIONAL private project" in admin.get("/admin").data
    assert admin.get(f"/admin/projects/{project_id}").status_code == 200
    assert submit(admin, f"/admin/projects/{project_id}").status_code == 400
    assert (
        submit(
            admin, f"/admin/projects/{project_id}", {"publish_brief": "yes"}
        ).status_code
        == 302
    )
    assert submit(admin, "/projects", {"workspace_id": project_id}).status_code == 404
    with hosted[0].extensions["web_store"].connection() as db:
        template_id = db.execute("SELECT id FROM brief_templates").fetchone()["id"]
    tester = actor("second@example.test")
    assert tester.get(f"/templates/{template_id}/start").status_code == 200
    assert (
        submit(
            tester,
            f"/templates/{template_id}/start",
            {"name": "FICTIONAL independent copy", "author": "second-fictional-tester"},
        ).status_code
        == 302
    )
    with tester.session_transaction() as session:
        copy_id = session["workspace_id"]
    root = hosted[0].extensions["web_store"].root / "projects"
    assert copy_id != project_id
    assert (root / copy_id / "brief.md").read_bytes() == (
        root / project_id / "brief.md"
    ).read_bytes()
    assert json.loads((root / copy_id / "project.json").read_text())["runs"] == {}
    assert not (root / copy_id / "ledger/events.jsonl").exists()


def test_duplicate_submissions_queue_once_and_reuse_completed_run(
    owner, pending, fake_sdk, hosted
):
    url, directory, _ = pending
    store = hosted[0].extensions["web_store"]
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    assert fake_sdk.responses.calls == 0
    assert owner.get(url).headers["Refresh"] == "5"
    assert submit(owner, "/project/upload").status_code == 409
    assert worker.work_once(store)
    assert fake_sdk.responses.calls == 1
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    assert not worker.work_once(store)
    assert b"Compare interpretations" in owner.get(url).data
    assert not (directory.parent.parent / "ledger/events.jsonl").exists()


def test_background_call_does_not_block_other_testers_or_draft_saves(
    owner, actor, pending, fake_sdk, hosted, answers, monkeypatch
):
    url, _, _ = pending
    store = hosted[0].extensions["web_store"]
    entered, release = Event(), Event()
    original = fake_sdk.responses.create

    def blocked(**kwargs):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(fake_sdk.responses, "create", blocked)
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(worker.work_once, store)
        try:
            assert entered.wait(3)
            assert actor("independent@example.test").get("/projects").status_code == 200
            assert owner.get(url).status_code == 200
            assert (
                submit(
                    owner, "/project/draft", {**answers, "draft_version": "0"}
                ).status_code
                == 302
            )
        finally:
            release.set()
        assert task.result(timeout=5)


def test_interrupted_worker_is_not_retried_automatically(owner, pending, hosted):
    url, _, project_id = pending
    store = hosted[0].extensions["web_store"]
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    job = store.claim_job()
    assert job is not None
    store.interrupt_running()
    assert not worker.work_once(store)
    with store.connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        assert row["state"] == "interrupted"
        assert row["allocated"] == 0
        assert (
            db.execute(
                "SELECT charged FROM spending WHERE project_id=?", (project_id,)
            ).fetchone()["charged"]
            == job["allocated"]
        )
    assert submit(owner, url, {"authorize": "yes"}).status_code == 400


def test_atomic_deployment_cap_and_duplicate_queue_requests(tmp_path):
    store = storage.WebStore(tmp_path)
    with store.connection(write=True) as db:
        for i in (1, 2):
            db.execute(
                "INSERT INTO users(id, issuer, subject) VALUES (?, 'fictional', ?)",
                (f"u{i}", f"s{i}"),
            )
            db.execute(
                "INSERT INTO projects(id, owner_id, name, author) VALUES (?, ?, "
                "'FICTIONAL', 'fictional')",
                (f"p{i}", f"u{i}"),
            )
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(
            pool.map(
                lambda i: store.enqueue(
                    f"p{i}",
                    "run",
                    Decimal("0.60"),
                    Decimal("0.60"),
                    Decimal("1.00"),
                    retry=False,
                ),
                (1, 2),
            )
        )
    assert len(set(jobs)) == 2
    with store.connection() as db:
        assert db.execute("SELECT SUM(allocated) FROM jobs").fetchone()[0] == 1_000_000
    repeated = store.enqueue(
        "p1", "run", Decimal("0.60"), Decimal("0.60"), Decimal("1.00"), retry=False
    )
    assert repeated in jobs
    with pytest.raises(ValueError, match="Another analysis"):
        store.enqueue(
            "p1",
            "other-run",
            Decimal("0.60"),
            Decimal("0.60"),
            Decimal("1.00"),
            retry=False,
        )


def test_local_projects_require_explicit_linking_to_verified_identity(
    project, tmp_path, hosted
):
    hosted_app, token = hosted
    settings = {
        key: hosted_app.config[key]
        for key in ("DATA_ROOT", "SECRET_KEY", "PROJECT_CONFIG", "TESTING")
    }
    local_app = web.create_app(
        {**settings, "AUTH_MODE": "local", "ACCESS_PASSWORD": ""}
    )
    local = local_app.test_client()
    assert local.get("/").status_code == 200
    assert (
        submit(
            local,
            "/create",
            {
                "name": "FICTIONAL local history",
                "author": "fictional",
                "brief_text": "FICTIONAL local brief.",
            },
        ).status_code
        == 302
    )
    signed = hosted_app.test_client()
    signed.environ_base["HTTP_CF_ACCESS_JWT_ASSERTION"] = token()
    cookie_name = local_app.config["SESSION_COOKIE_NAME"]
    signed.set_cookie(cookie_name, local.get_cookie(cookie_name).value)
    assert b"Link my local projects" in signed.get("/").data
    assert b"FICTIONAL local history" not in signed.get("/projects").data
    assert submit(signed, "/claim-local-projects").status_code == 302
    assert b"FICTIONAL local history" in signed.get("/projects").data


def test_failed_job_retains_charges_and_requires_explicit_retry(
    owner, pending, fake_sdk, hosted, monkeypatch
):
    url, _, project_id = pending
    store = hosted[0].extensions["web_store"]
    original = fake_sdk.responses.create

    def failure(**_kwargs):
        raise RuntimeError("DO-NOT-EXPOSE-FAKE-API-KEY")

    monkeypatch.setattr(fake_sdk.responses, "create", failure)
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    assert worker.work_once(store)
    with store.connection() as db:
        assert db.execute("SELECT state FROM jobs").fetchone()["state"] == "failed"
        charge = db.execute(
            "SELECT charged FROM spending WHERE project_id=?", (project_id,)
        ).fetchone()["charged"]
        assert charge == 2200
        assert db.execute("SELECT SUM(allocated) FROM jobs").fetchone()[0] == 0
    response = owner.get(url)
    assert b"DO-NOT-EXPOSE" not in response.data
    assert b"RuntimeError" in response.data
    assert submit(owner, url, {"authorize": "yes"}).status_code == 400
    monkeypatch.setattr(fake_sdk.responses, "create", original)
    assert (
        submit(owner, url, {"authorize": "yes", "retry_failed": "yes"}).status_code
        == 302
    )
    assert worker.work_once(store)
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT charged FROM spending WHERE project_id=?", (project_id,)
            ).fetchone()["charged"]
            == 4400
        )


def test_auth_settings_fail_closed_and_numeric_zero_disables_budget(project, tmp_path):
    settings = {
        "TESTING": True,
        "PROJECT_CONFIG": project,
        "DATA_ROOT": tmp_path / "config-data",
        "SECRET_KEY": "fictional",
    }
    with pytest.raises(ValueError, match="WEB_AUTH_MODE"):
        web.create_app({**settings, "AUTH_MODE": "unexpected"})
    with pytest.raises(ValueError, match="WEB_ACCESS_TEAM_DOMAIN"):
        web.create_app(
            {
                **settings,
                "AUTH_MODE": "cloudflare",
                "ACCESS_TEAM_DOMAIN": "",
                "ACCESS_AUD": "",
            }
        )
    app = web.create_app(
        {
            **settings,
            "AUTH_MODE": "local",
            "RUN_BUDGET_USD": "0.10",
            "USER_BUDGET_USD": 0,
            "LIVE_ENABLED": True,
        }
    )
    client = app.test_client()
    client.get("/")
    assert (
        submit(
            client,
            "/create",
            {
                "name": "FICTIONAL",
                "author": "fictional",
                "brief_text": "FICTIONAL budget test.",
            },
        ).status_code
        == 302
    )
    assert b"Real AI requests are disabled" in client.get("/project").data


def test_application_never_serves_repository_or_database_files(owner):
    for path in (
        "/README.md",
        "/agentic_dt/model.py",
        "/web.sqlite3",
        "/extensions/web/deployment.env",
    ):
        assert owner.get(path).status_code == 404


def test_queue_survives_metadata_reopening_and_keeps_pending_quota(
    owner, pending, hosted
):
    url, _, _ = pending
    store = hosted[0].extensions["web_store"]
    assert submit(owner, url, {"authorize": "yes"}).status_code == 302
    reopened = storage.WebStore(store.root)
    with reopened.connection() as db:
        job = db.execute("SELECT * FROM jobs").fetchone()
        assert job["state"] == "queued"
        assert job["allocated"] == 10000


def test_compose_keeps_secrets_and_origin_private():
    definition = web.yaml.safe_load(
        (web.ROOT / "extensions/web/compose.yaml").read_text()
    )
    services = definition["services"]
    assert set(services) == {"web", "worker", "cloudflared"}
    assert "ports" not in services["web"]
    assert "OPENAI_API_KEY" not in services["web"]["environment"]
    assert "OPENAI_API_KEY" in services["worker"]["environment"]
    assert services["worker"]["volumes"] == services["web"]["volumes"]
    assert services["web"]["environment"]["WEB_AUTH_MODE"] == "cloudflare"
    assert services["worker"]["stop_grace_period"] == "10m"


def test_database_initializes_across_simultaneous_cold_processes(tmp_path):
    command = [
        sys.executable,
        "-c",
        "import sys; from pathlib import Path; "
        "from extensions.web.storage import WebStore; "
        "WebStore(Path(sys.argv[1])); print('ready')",
        str(tmp_path),
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _index: subprocess.run(
                    command, cwd=web.ROOT, capture_output=True, text=True, timeout=10
                ),
                range(4),
            )
        )
    for result in results:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ready"
