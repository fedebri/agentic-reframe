"""Plain HTML adapter for the existing inquiry workflow, with isolated storage."""

import hmac
import io
import json
import os
import secrets
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import yaml
from flask import (
    Flask,
    abort,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from openai import APIError
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from agentic_dt.graph import replay
from agentic_dt.reports import compile_reports
from agentic_dt.review import apply_review, export_review, load_completed_run
from agentic_dt.schemas import HumanFrame, ReviewWorksheet, RunManifest
from agentic_dt.workflow import run_exercise, validate_project

from .identity import AccessIdentity
from .storage import WebStore, budget_units
from .storage import reserved as _reserved
from .worker import public_error

ROOT = Path(__file__).resolve().parents[2]


def _uploaded_text(upload: FileStorage, limit: int) -> tuple[str, str]:
    """Accept bounded UTF-8 documents at the browser upload boundary."""
    name = secure_filename(upload.filename or "")
    if Path(name).suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Upload a Markdown (.md) or plain text (.txt) file.")
    raw = upload.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{name}: the file exceeds the {limit:,} byte limit.")
    text = raw.decode("utf-8")
    if not text.strip() or "\x00" in text:
        raise ValueError(f"{name}: upload a nonempty UTF-8 text document.")
    return name, text


def _save_index(directory: Path, data: dict) -> None:
    """Atomically save the web index; provenance is owned by the core runtime."""
    temporary = directory / "project.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "project.json")


def _research_archive(directory: Path) -> io.BytesIO:
    """Share report export plumbing between project owners and cohort administrators."""
    snapshot = directory / "reports" / uuid4().hex
    compile_reports(directory / "ledger/events.jsonl", snapshot)
    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for name in ("design_research_brief.md", "synthesis_index.json"):
            bundle.write(snapshot / name, name)
        bundle.write(directory / "ledger/events.jsonl", "ledger/events.jsonl")
    archive.seek(0)
    return archive


def create_app(
    settings: dict | None = None,
    *,
    store: WebStore | None = None,
    access: AccessIdentity | None = None,
) -> Flask:
    """Create the optional web app without changing repository inputs or outputs."""
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_ROOT=Path(
            os.environ.get("WEB_DATA_ROOT", Path(__file__).parent / ".data")
        ),
        PROJECT_CONFIG=ROOT / "config/project.yaml",
        SECRET_KEY=os.environ.get("WEB_SECRET_KEY"),
        ACCESS_PASSWORD=os.environ.get("WEB_ACCESS_PASSWORD", ""),
        RUN_BUDGET_USD=os.environ.get("WEB_RUN_BUDGET_USD", "0"),
        PROJECT_BUDGET_USD=os.environ.get("WEB_PROJECT_BUDGET_USD", "0.50"),
        USER_BUDGET_USD=os.environ.get("WEB_USER_BUDGET_USD"),
        TOTAL_BUDGET_USD=os.environ.get("WEB_TOTAL_BUDGET_USD", "5.00"),
        BUDGETS_ENABLED=os.environ.get("WEB_BUDGETS_ENABLED", "1") == "1",
        LIVE_ENABLED=(os.environ["WEB_LIVE_ENABLED"] == "1")
        if "WEB_LIVE_ENABLED" in os.environ
        else None,
        AUTH_MODE=os.environ.get("WEB_AUTH_MODE", "local"),
        ACCESS_TEAM_DOMAIN=os.environ.get("WEB_ACCESS_TEAM_DOMAIN", ""),
        ACCESS_AUD=os.environ.get("WEB_ACCESS_AUD", ""),
        ADMIN_EMAILS=os.environ.get("WEB_ADMIN_EMAILS", ""),
        MAX_CONTENT_LENGTH=1_000_000,
        SESSION_COOKIE_NAME="agentic_reframe_web",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("WEB_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    if settings:
        app.config.update(settings)
    data_root = Path(app.config["DATA_ROOT"]).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        import fcntl

        key_path = data_root / ".session-key"
        with (data_root / ".initialization-lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not key_path.exists():
                key_path.write_text(secrets.token_hex(32), encoding="utf-8")
                key_path.chmod(0o600)
            app.config["SECRET_KEY"] = key_path.read_text(encoding="utf-8")
    source_config = Path(app.config["PROJECT_CONFIG"]).resolve()
    source_root = source_config.parent.parent
    configuration = validate_project(source_config)
    interpretation_prompts = yaml.safe_load(
        Path(__file__).with_name("interpretations.yaml").read_text(encoding="utf-8")
    )
    run_cap = Decimal(app.config["RUN_BUDGET_USD"])
    user_cap = Decimal(
        app.config["USER_BUDGET_USD"]
        if app.config["USER_BUDGET_USD"] is not None
        else app.config["PROJECT_BUDGET_USD"]
    )
    total_cap = Decimal(app.config["TOTAL_BUDGET_USD"])
    budgets_enabled = app.config["BUDGETS_ENABLED"]
    if not all(
        value.is_finite() and value >= 0 for value in (run_cap, user_cap, total_cap)
    ):
        raise ValueError("Web budgets must be finite, nonnegative USD amounts.")
    if app.config["AUTH_MODE"] not in {"local", "cloudflare"}:
        raise ValueError("WEB_AUTH_MODE must be local or cloudflare.")
    if app.config["AUTH_MODE"] == "cloudflare":
        access = access or AccessIdentity(
            app.config["ACCESS_TEAM_DOMAIN"], app.config["ACCESS_AUD"]
        )
        app.config["SESSION_COOKIE_SECURE"] = True
    admins = {
        email.strip().casefold()
        for email in app.config["ADMIN_EMAILS"].split(",")
        if email.strip()
    }
    store = store or WebStore(data_root)
    app.extensions["web_store"] = store

    @app.before_request
    def request_boundary():
        if request.endpoint == "health":
            return
        session.permanent = True
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if access is not None:
            import jwt

            token = request.headers.get("Cf-Access-Jwt-Assertion")
            if not token:
                abort(
                    401,
                    "Sign in through this application's Cloudflare Access hostname.",
                )
            try:
                identity = access.authenticate(token)
            except jwt.PyJWKClientConnectionError:
                abort(
                    503,
                    "Cloudflare signing keys are temporarily unavailable. Try "
                    "signing in again shortly.",
                )
            except (jwt.InvalidTokenError, jwt.PyJWKClientError):
                abort(
                    401,
                    "Cloudflare Access sign-in is invalid or expired. Sign in again.",
                )
            g.user = store.user(identity.issuer, identity.subject, identity.email)
        else:
            subject = session.setdefault("local_subject", uuid4().hex)
            g.user = store.user("local", subject, None)
        previous_user = session.get("user_id")
        if previous_user and previous_user != g.user["id"]:
            with store.connection() as db:
                previous = db.execute(
                    "SELECT * FROM users WHERE id=?", (previous_user,)
                ).fetchone()
            if (
                previous
                and previous["issuer"] == "local"
                and previous["subject"] == session.get("local_subject")
            ):
                session["claim_local_user"] = previous_user
            else:
                session.pop("claim_local_user", None)
            session.pop("workspace_id", None)
            session["csrf"] = secrets.token_urlsafe(32)
        if previous_user in {None, g.user["id"]}:
            legacy = session.pop("workspace_ids", [])
            if session.get("workspace_id") and session["workspace_id"] not in legacy:
                legacy.append(session["workspace_id"])
            store.claim_legacy(g.user["id"], legacy)
        session["user_id"] = g.user["id"]
        g.is_admin = access is not None and g.user["email"] in admins
        if request.method == "POST" and not hmac.compare_digest(
            request.form.get("csrf", ""), session["csrf"]
        ):
            abort(400, "The form expired. Reload the page and try again.")
        if (
            access is None
            and app.config["ACCESS_PASSWORD"]
            and not session.get("access_granted")
            and request.endpoint not in {"login", "health"}
        ):
            return redirect(url_for("login"))
        if request.path.startswith("/admin") and not g.is_admin:
            abort(403, "Administrator access is required.")
        if request.path.startswith("/project") and request.endpoint != "projects":
            if "workspace_id" not in session:
                abort(404)
            with store.connection() as db:
                g.project_record = db.execute(
                    "SELECT * FROM projects WHERE id=? AND owner_id=?",
                    (session["workspace_id"], g.user["id"]),
                ).fetchone()
            if g.project_record is None:
                abort(404)
            if request.method == "POST":
                posted_project = request.form.get("project_id")
                if (
                    posted_project is not None or access is not None
                ) and posted_project != session["workspace_id"]:
                    abort(
                        409,
                        "The active project changed. Reload the project before "
                        "submitting.",
                    )
            g.storage_lock = store.project_lock(
                session["workspace_id"],
                shared=request.method == "GET"
                and request.endpoint not in {"review", "run"},
            )
            g.storage_lock.__enter__()
            with store.connection() as db:
                busy = db.execute(
                    "SELECT id FROM jobs WHERE project_id=? AND state IN ('queued',"
                    " 'running')",
                    (session["workspace_id"],),
                ).fetchone()
            if (
                busy
                and request.method == "POST"
                and request.endpoint not in {"run", "save_draft"}
            ):
                abort(
                    409,
                    "An analysis is queued or running. You can read the project and"
                    " save drafts; wait before changing its research history.",
                )
            g.directory = data_root / "projects" / session["workspace_id"]
            g.project = json.loads((g.directory / "project.json").read_text())

    @app.teardown_request
    def release_storage_lock(_error):
        lock = g.pop("storage_lock", None)
        if lock is not None:
            lock.__exit__(None, None, None)

    @app.after_request
    def private_response(response):
        if (
            request.method == "POST"
            and response.status_code < 400
            and hasattr(g, "project_record")
        ):
            with store.connection(write=True) as db:
                db.execute(
                    "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', "
                    "'now') WHERE id=?",
                    (g.project_record["id"],),
                )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
            "form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.context_processor
    def form_context():
        project_choices = []
        if hasattr(g, "user"):
            with store.connection() as db:
                project_choices = db.execute(
                    "SELECT id, name FROM projects WHERE owner_id=? "
                    "ORDER BY updated_at DESC, rowid DESC",
                    (g.user["id"],),
                ).fetchall()
        return {
            "csrf": session["csrf"],
            "live_available": (
                (
                    not budgets_enabled
                    or (run_cap > 0 and user_cap > 0 and total_cap > 0)
                )
                and (
                    app.config["LIVE_ENABLED"]
                    if app.config["LIVE_ENABLED"] is not None
                    else bool(os.environ.get("OPENAI_API_KEY"))
                )
            ),
            "signed_in": access is not None,
            "is_admin": getattr(g, "is_admin", False),
            "identity_email": g.user["email"] if hasattr(g, "user") else None,
            "project_id": session.get("workspace_id"),
            "project_choices": project_choices,
            "budgets_enabled": budgets_enabled,
        }

    @app.errorhandler(ValueError)
    @app.errorhandler(yaml.YAMLError)
    def invalid_input(error):
        return render_template("error.html", message=str(error)), 422

    @app.errorhandler(APIError)
    def service_error(error):
        # SDK exception messages can contain request/response data. Expose only
        # the public identifiers needed to investigate a failed provider call.
        message = public_error(error)
        return render_template("error.html", message=message), 502

    @app.errorhandler(HTTPException)
    def http_error(error):
        return render_template("error.html", message=error.description), error.code

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if not hmac.compare_digest(
                request.form.get("password", "").encode(),
                app.config["ACCESS_PASSWORD"].encode(),
            ):
                return render_template("login.html", incorrect=True), 403
            session["access_granted"] = True
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.get("/")
    def home():
        with store.connection() as db:
            templates = db.execute(
                "SELECT id, name FROM brief_templates ORDER BY created_at DESC"
            ).fetchall()
        return render_template(
            "home.html", has_project="workspace_id" in session, templates=templates
        )

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(
            "/cdn-cgi/access/logout" if access is not None else url_for("home")
        )

    @app.post("/claim-local-projects")
    def claim_local_projects():
        if access is None or not session.get("claim_local_user"):
            abort(400, "There are no browser-owned projects to link to this sign-in.")
        with store.connection(write=True) as db:
            previous = db.execute(
                "SELECT * FROM users WHERE id=? AND issuer='local' AND subject=?",
                (session["claim_local_user"], session.get("local_subject")),
            ).fetchone()
            if previous is None:
                abort(403)
            db.execute(
                "UPDATE projects SET owner_id=? WHERE owner_id=?",
                (g.user["id"], previous["id"]),
            )
        session.pop("claim_local_user")
        return redirect(url_for("projects"))

    def create_workspace(name: str, author: str, brief: str) -> str:
        """Create private storage and ownership for fresh projects or brief copies."""
        workspace_id = uuid4().hex
        directory = data_root / "projects" / workspace_id
        (directory / "config").mkdir(parents=True)
        (directory / "uploads").mkdir()
        (directory / "brief.md").write_text(brief, encoding="utf-8")
        config = configuration.model_dump(mode="json")
        config["project"]["name"] = name
        config["paths"] = {
            "brief": str(directory / "brief.md"),
            "outputs": str(directory / "runs"),
            "ledger": str(directory / "ledger/events.jsonl"),
        }
        for key in ("analyst_prompt", "critic_prompt"):
            config["workflow"][key] = str(source_root / config["workflow"][key])
        for exercise in config["exercises"]:
            exercise["source"] = str(source_root / exercise["source"])
        (directory / "config/project.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        _save_index(
            directory, {"name": name, "author": author, "uploads": [], "runs": {}}
        )
        with store.connection(write=True) as db:
            db.execute(
                "INSERT INTO projects(id, owner_id, name, author) VALUES (?, ?, ?, ?)",
                (workspace_id, g.user["id"], name, author),
            )
        session["workspace_id"] = workspace_id
        return workspace_id

    @app.post("/create")
    def create_project():
        previous_id = session.get("workspace_id")
        if previous_id and request.form.get("restart_from") != previous_id:
            abort(409, "The active project changed. Open a fresh restart form.")
        name = request.form["name"].strip()
        author = request.form["author"].strip()
        if not name or not author:
            raise ValueError("Enter a project name and your name.")
        upload = request.files.get("brief")
        if upload and upload.filename:
            _, brief = _uploaded_text(upload, configuration.model.max_input_bytes)
        else:
            brief = request.form.get("brief_text", "").strip()
            if not brief or len(brief.encode()) > configuration.model.max_input_bytes:
                raise ValueError(
                    "Enter a challenge brief within the upload size limit."
                )
        create_workspace(name, author, brief)
        return redirect(url_for("project"))

    @app.route("/templates/<template_id>/start", methods=["GET", "POST"])
    def start_template(template_id):
        with store.connection() as db:
            template = db.execute(
                "SELECT * FROM brief_templates WHERE id=?", (template_id,)
            ).fetchone()
        if template is None:
            abort(404)
        if request.method == "POST":
            author = request.form["author"].strip()
            name = request.form["name"].strip()
            if not author or not name:
                raise ValueError("Enter a project name and your name.")
            create_workspace(name, author, template["brief"])
            return redirect(url_for("project"))
        return render_template("template_start.html", template=template)

    @app.get("/project/restart")
    def restart():
        blank = request.args.get("blank") == "1"
        draft = (
            {}
            if blank
            else {
                **g.project,
                "brief_text": (g.directory / "brief.md").read_text(),
            }
        )
        return render_template(
            "restart.html",
            draft=draft,
            blank=blank,
            restart_from=session["workspace_id"],
        )

    @app.route("/projects", methods=["GET", "POST"])
    def projects():
        if request.method == "POST":
            workspace_id = request.form["workspace_id"]
            with store.connection() as db:
                owned = db.execute(
                    "SELECT id FROM projects WHERE id=? AND owner_id=?",
                    (workspace_id, g.user["id"]),
                ).fetchone()
            if owned is None:
                abort(404)
            session["workspace_id"] = workspace_id
            return redirect(url_for("project"))
        with store.connection() as db:
            saved = db.execute(
                "SELECT * FROM projects WHERE owner_id=? ORDER BY updated_at DESC, "
                "rowid DESC",
                (g.user["id"],),
            ).fetchall()
        return render_template("projects.html", projects=saved)

    @app.get("/project")
    def project():
        exercise = configuration.exercise(
            request.args.get("exercise", "frame_challenge")
        )
        runs = []
        with store.connection() as db:
            jobs = db.execute(
                "SELECT * FROM jobs WHERE project_id=? ORDER BY rowid",
                (session["workspace_id"],),
            ).fetchall()
            drafts = {
                row["exercise_id"]: {
                    "version": row["version"],
                    "data": json.loads(row["data"]),
                }
                for row in db.execute(
                    "SELECT * FROM drafts WHERE project_id=?",
                    (session["workspace_id"],),
                )
            }
        latest_jobs = {job["run_id"]: job for job in jobs}
        for run_id, item in g.project["runs"].items():
            directory = g.directory / "runs" / run_id
            job = latest_jobs.get(run_id)
            status = (
                {"state": job["state"]}
                if job
                and job["state"] in {"queued", "running", "failed", "interrupted"}
                else json.loads((directory / "status.json").read_text())
            )
            runs.append({"id": run_id, **item, "state": status["state"]})
        state = replay(g.directory / "ledger/events.jsonl")
        return render_template(
            "project.html",
            project=g.project,
            brief=(g.directory / "brief.md").read_text(),
            exercises=configuration.exercises,
            exercise=exercise,
            instructions={
                item.id: (source_root / item.source).read_text()
                for item in configuration.exercises
            },
            interpretation_prompts=interpretation_prompts,
            saved_drafts=drafts,
            draft=drafts.get(exercise.id, {"version": 0, "data": {}}),
            uploads=[
                {
                    **item,
                    "content": (g.directory / "uploads" / item["file"]).read_text(),
                }
                for item in g.project["uploads"]
            ],
            context=state.context_claims(),
            runs=runs,
            has_reviews=bool(state.claims),
            limit=configuration.model.max_input_bytes,
            draft_saved=request.args.get("saved") == "1" and exercise.id in drafts,
        )

    @app.post("/project/draft")
    def save_draft():
        exercise_id = request.form["exercise"]
        configuration.exercise(exercise_id)
        data = {
            name: request.form.get(name, "")
            for name in (
                "framing",
                "observations",
                "assumptions",
                "alternative_frame",
                "open_questions",
            )
        }
        data.update(
            evidence=request.form.getlist("evidence"),
            context=request.form.getlist("context"),
            critic=request.form.get("critic") == "yes",
        )
        if not set(data["evidence"]) <= {item["id"] for item in g.project["uploads"]}:
            abort(400, "Choose evidence uploaded to this project.")
        serialized = json.dumps(data)
        if len(serialized.encode()) > configuration.model.max_input_bytes:
            raise ValueError(
                f"Draft exceeds the {configuration.model.max_input_bytes:,} byte limit."
            )
        version = int(request.form.get("draft_version", "0"))
        with store.connection(write=True) as db:
            changed = db.execute(
                "INSERT INTO drafts(project_id, exercise_id, data, version) VALUES "
                "(?, ?, ?, 1) "
                "ON CONFLICT(project_id, exercise_id) DO UPDATE SET "
                "data=excluded.data, version=drafts.version+1, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE "
                "drafts.version=? RETURNING version",
                (session["workspace_id"], exercise_id, serialized, version),
            ).fetchone()
            if changed is None or (version != 0 and changed["version"] == 1):
                abort(
                    409,
                    "This draft changed on another page or machine. Your submitted "
                    "text is below; reload before saving again.",
                )
            db.execute(
                "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', "
                "'now') WHERE id=?",
                (session["workspace_id"],),
            )
        return redirect(
            url_for(
                "project",
                exercise=exercise_id,
                saved="1",
                _anchor="independent-interpretation",
            )
        )

    @app.post("/project/upload")
    def upload_evidence():
        exercise = configuration.exercise(
            request.form.get("exercise", "frame_challenge")
        )
        uploads = [item for item in request.files.getlist("evidence") if item.filename]
        if not uploads:
            raise ValueError("Choose at least one evidence document.")
        documents = [
            _uploaded_text(item, configuration.model.max_input_bytes)
            for item in uploads
        ]
        for name, text in documents:
            document_id = uuid4().hex
            filename = f"{document_id}_{name}"
            (g.directory / "uploads" / filename).write_text(text, encoding="utf-8")
            g.project["uploads"].append(
                {"id": document_id, "name": name, "file": filename}
            )
        _save_index(g.directory, g.project)
        return redirect(url_for("project", exercise=exercise.id, _anchor="exercise"))

    @app.post("/project/prepare")
    def prepare():
        exercise_id = request.form["exercise"]
        configuration.exercise(exercise_id)
        frame = HumanFrame(
            author_id=g.project["author"],
            exercise_id=exercise_id,
            framing=request.form["framing"],
            observations=request.form["observations"].splitlines(),
            assumptions=request.form["assumptions"].splitlines(),
            alternative_frame=request.form["alternative_frame"],
            open_questions=request.form["open_questions"].splitlines(),
        )
        selected = request.form.getlist("evidence")
        known = {item["id"]: item["file"] for item in g.project["uploads"]}
        if not set(selected) <= known.keys():
            abort(400, "Choose evidence uploaded to this project.")
        run_id = uuid4().hex
        directory = g.directory / "runs" / run_id
        (g.directory / "frames").mkdir(exist_ok=True)
        frame_path = g.directory / "frames" / f"{run_id}.yaml"
        frame_path.write_text(
            yaml.safe_dump(frame.model_dump(), sort_keys=False), encoding="utf-8"
        )
        critic = request.form.get("critic") == "yes"
        run_exercise(
            g.directory / "config/project.yaml",
            exercise_id,
            directory,
            [g.directory / "uploads" / known[item] for item in selected],
            critic,
            False,
            None,
            context_claim_ids=request.form.getlist("context"),
            human_frame_path=frame_path,
        )
        g.project["runs"][run_id] = {"exercise": exercise_id}
        _save_index(g.directory, g.project)
        return redirect(url_for("run", run_id=run_id))

    @app.route("/project/runs/<run_id>", methods=["GET", "POST"])
    def run(run_id):
        if run_id not in g.project["runs"]:
            abort(404)
        directory = g.directory / "runs" / run_id
        manifest = RunManifest.model_validate_json(
            (directory / "input_manifest.json").read_bytes()
        )
        with store.connection() as db:
            job = db.execute(
                "SELECT * FROM jobs WHERE project_id=? AND run_id=? ORDER BY rowid "
                "DESC LIMIT 1",
                (session["workspace_id"], run_id),
            ).fetchone()
        active = job is not None and job["state"] in {"queued", "running"}
        status = (
            {"state": job["state"]}
            if job is not None
            and job["state"] in {"queued", "running", "failed", "interrupted"}
            else json.loads((directory / "status.json").read_text())
        )
        # Import reservations from runs prepared by the earlier adapter.
        if not active and job is None:
            with store.connection(write=True) as db:
                db.execute(
                    "INSERT INTO spending(project_id, run_id, charged) VALUES (?, "
                    "?, ?) ON CONFLICT(project_id, run_id) DO UPDATE SET "
                    "charged=max(charged, excluded.charged)",
                    (
                        session["workspace_id"],
                        run_id,
                        budget_units(_reserved(directory)),
                    ),
                )
        with store.connection() as db:
            remaining = (
                store.available(
                    db, session["workspace_id"], run_id, run_cap, user_cap, total_cap
                )
                if budgets_enabled
                else 0
            )
            charge = db.execute(
                "SELECT charged FROM spending WHERE project_id=? AND run_id=?",
                (session["workspace_id"], run_id),
            ).fetchone()["charged"]
        charged = Decimal(charge) / 1_000_000
        budget = charged + max(Decimal(remaining) / 1_000_000, Decimal("0"))
        estimated_cost = None
        if not budgets_enabled:
            # The unchanged core requires finite accounting authority. Cover every
            # permitted token/retry for both steps without imposing a dollar cap.
            model = manifest.model
            estimated_cost = (
                (
                    model.max_input_tokens * Decimal(model.input_usd_per_million)
                    + model.max_output_tokens * Decimal(model.output_usd_per_million)
                )
                / 1_000_000
                * (model.max_retries + 1)
                * (2 if manifest.critic_enabled else 1)
            )
        live_enabled = form_context()["live_available"]
        if request.method == "POST":
            if not live_enabled:
                abort(403, "Live AI calls have not been enabled by the host.")
            if request.form.get("authorize") != "yes":
                abort(400, "Authorize the paid analysis before running AI.")
            if status["state"] in {"awaiting_review", "completed"}:
                return redirect(url_for("run", run_id=run_id))
            if (
                not active
                and (
                    status["state"] in {"failed", "running"}
                    or job
                    and job["state"] in {"failed", "interrupted"}
                )
                and request.form.get("retry_failed") != "yes"
            ):
                abort(
                    400,
                    "Explicitly authorize retrying this failed or interrupted "
                    "analysis.",
                )
            try:
                store.enqueue(
                    session["workspace_id"],
                    run_id,
                    run_cap,
                    user_cap,
                    total_cap,
                    retry=request.form.get("retry_failed") == "yes",
                    estimated_cost=estimated_cost,
                )
            except ValueError as error:
                abort(400, str(error))
            return redirect(url_for("run", run_id=run_id))
        worksheet = directory / "review.yaml"
        completed = status["state"] in {"awaiting_review", "completed"}
        analysis = critique = None
        citations = []
        if completed:
            _, analysis, critique = load_completed_run(directory)
            citations = list(
                dict.fromkeys(
                    citation
                    for claim in analysis.claims
                    for citation in claim.citations
                )
            )
        if completed and not worksheet.exists():
            export_review(directory, worksheet, g.project["author"])
        response = app.make_response(
            render_template(
                "run.html",
                run_id=run_id,
                manifest=manifest,
                status=status,
                frame=yaml.safe_load(manifest.human_frame.content),
                request_text=(directory / "analyst_request.json").read_text(),
                analysis=analysis,
                critique=critique,
                citations=citations,
                live_enabled=live_enabled,
                budget=max(budget, Decimal("0")),
                reserved=charged,
                run_cap=run_cap,
                job=job,
                completed=completed,
                reviewed=worksheet.with_suffix(".receipt.json").exists(),
            )
        )
        if active:
            response.headers["Refresh"] = "5"
        return response

    @app.route("/project/runs/<run_id>/review", methods=["GET", "POST"])
    def review(run_id):
        if run_id not in g.project["runs"]:
            abort(404)
        directory = g.directory / "runs" / run_id
        manifest, analysis, critique = load_completed_run(directory)
        worksheet = directory / "review.yaml"
        if not worksheet.exists():
            export_review(directory, worksheet, g.project["author"])
        applied = worksheet.with_suffix(".receipt.json").exists()
        data = yaml.safe_load(worksheet.read_text())
        if request.method == "POST":
            if applied or worksheet.with_suffix(".batch.json").exists():
                # Retrying a commit reuses its exact saved decisions and batch.
                apply_review(worksheet)
                return redirect(url_for("run", run_id=run_id))
            for index, decision in enumerate(data["decisions"]):
                action = request.form[f"decision_{index}"]
                revision = request.form.get(f"revision_{index}", "").strip() or None
                confidence = request.form.get(f"confidence_{index}") or None
                if action == "revise" and (not revision or confidence is None):
                    raise ValueError(
                        f"Claim {index + 1}: Revise requires revised wording "
                        "and your confidence (0–1)."
                    )
                if action in {"keep", "exclude"}:
                    revision = confidence = None
                # Keep the stored contract and accept/reject submissions from
                # forms opened before the review labels changed.
                decision.update(
                    decision={
                        "keep": "accept",
                        "revise": "accept",
                        "exclude": "reject",
                    }.get(action, action),
                    validation_status=(
                        "proposed"
                        if action == "exclude"
                        and request.form[f"status_{index}"] == "supported"
                        else request.form[f"status_{index}"]
                    ),
                    public_reasoning_summary=request.form[f"reason_{index}"],
                    revised_statement=revision,
                    revision_confidence=confidence,
                )
            data["reflection"] = {
                "revised_frame": request.form["revised_frame"],
                "disagreement": request.form["disagreement"],
                "assumptions_reconsidered": request.form[
                    "assumptions_reconsidered"
                ].splitlines(),
                "next_research_question": request.form["next_research_question"],
                "revision_trigger": request.form["revision_trigger"],
                "evidence_refs": request.form.getlist("reflection_evidence"),
            }
            validated = ReviewWorksheet.model_validate(data)
            worksheet.write_text(
                yaml.safe_dump(validated.model_dump(mode="json"), sort_keys=False),
                encoding="utf-8",
            )
            apply_review(worksheet)
            return redirect(url_for("run", run_id=run_id))
        questions = (
            [critique.next_question] if critique and critique.next_question else []
        )
        questions.extend(
            question for claim in analysis.claims for question in claim.open_questions
        )
        return render_template(
            "review.html",
            run_id=run_id,
            analysis=analysis,
            critique=critique,
            manifest=manifest,
            data=data,
            citations=list(
                dict.fromkeys(
                    citation
                    for claim in analysis.claims
                    for citation in claim.citations
                )
            ),
            applied=applied,
            prepared=worksheet.with_suffix(".batch.json").exists(),
            investigation_questions=list(dict.fromkeys(questions)),
        )

    @app.post("/project/export")
    def export():
        if not (g.directory / "ledger/events.jsonl").exists():
            abort(400, "Apply a human review before exporting your research.")
        return send_file(
            _research_archive(g.directory),
            mimetype="application/zip",
            as_attachment=True,
            download_name="research-report.zip",
        )

    @app.get("/admin")
    def admin():
        with store.connection() as db:
            cohort = db.execute(
                "SELECT p.*, u.email, u.issuer, "
                "(SELECT COALESCE(SUM(charged), 0) FROM spending WHERE "
                "project_id=p.id) AS charged, "
                "(SELECT COALESCE(SUM(allocated), 0) FROM jobs WHERE "
                "project_id=p.id AND state IN ('queued', 'running')) AS pending "
                "FROM projects p JOIN users u ON p.owner_id=u.id ORDER BY "
                "p.updated_at DESC, p.rowid DESC"
            ).fetchall()
            jobs = db.execute(
                "SELECT j.*, p.name, u.email FROM jobs j JOIN projects p ON "
                "p.id=j.project_id "
                "JOIN users u ON u.id=p.owner_id ORDER BY j.rowid DESC LIMIT 50"
            ).fetchall()
            templates = db.execute(
                "SELECT id, name FROM brief_templates ORDER BY created_at DESC"
            ).fetchall()
        return render_template(
            "admin.html",
            projects=cohort,
            jobs=jobs,
            templates=templates,
            total_cap=total_cap,
        )

    @app.route("/admin/projects/<workspace_id>", methods=["GET", "POST"])
    def admin_project(workspace_id):
        with store.connection() as db:
            record = db.execute(
                "SELECT p.*, u.email FROM projects p JOIN users u ON "
                "u.id=p.owner_id WHERE p.id=?",
                (workspace_id,),
            ).fetchone()
        if record is None:
            abort(404)
        directory = data_root / "projects" / workspace_id
        with store.project_lock(workspace_id):
            metadata = json.loads((directory / "project.json").read_text())
            brief = (directory / "brief.md").read_text()
            if request.method == "POST":
                if request.form.get("publish_brief") != "yes":
                    abort(
                        400,
                        "Confirm that this brief may be shared with all invited "
                        "testers.",
                    )
                with store.connection(write=True) as db:
                    db.execute(
                        "INSERT INTO brief_templates(id, name, brief, created_by) "
                        "VALUES (?, ?, ?, ?)",
                        (uuid4().hex, record["name"], brief, g.user["id"]),
                    )
                return redirect(url_for("admin"))
            with store.connection() as db:
                job_rows = db.execute(
                    "SELECT * FROM jobs WHERE project_id=? ORDER BY rowid",
                    (workspace_id,),
                ).fetchall()
                drafts = db.execute(
                    "SELECT exercise_id, updated_at FROM drafts WHERE project_id=? "
                    "ORDER BY exercise_id",
                    (workspace_id,),
                ).fetchall()
            latest = {job["run_id"]: job for job in job_rows}
            runs = []
            for run_id, item in metadata["runs"].items():
                job = latest.get(run_id)
                status = (
                    job["state"]
                    if job and job["state"] in {"queued", "running"}
                    else json.loads(
                        (directory / "runs" / run_id / "status.json").read_text()
                    )["state"]
                )
                runs.append({"id": run_id, **item, "state": status})
            return render_template(
                "admin_project.html",
                record=record,
                brief=brief,
                project=metadata,
                runs=runs,
                drafts=drafts,
                has_reviews=(directory / "ledger/events.jsonl").exists(),
            )

    @app.post("/admin/projects/<workspace_id>/export")
    def admin_export(workspace_id):
        with store.connection() as db:
            record = db.execute(
                "SELECT id FROM projects WHERE id=?", (workspace_id,)
            ).fetchone()
            active = db.execute(
                "SELECT id FROM jobs WHERE project_id=? AND state IN ('queued', "
                "'running')",
                (workspace_id,),
            ).fetchone()
        if record is None:
            abort(404)
        if active:
            abort(409, "Wait for this project's analysis to finish before exporting.")
        directory = data_root / "projects" / workspace_id
        with store.project_lock(workspace_id):
            if not (directory / "ledger/events.jsonl").exists():
                abort(400, "This project has no applied human review to export yet.")
            return send_file(
                _research_archive(directory),
                mimetype="application/zip",
                as_attachment=True,
                download_name=f"research-{workspace_id[:8]}.zip",
            )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8787, debug=False, threaded=False)
