"""Offline browser-boundary tests for the optional website adapter."""

import importlib
import io
import json
import re
import sys
from contextlib import nullcontext
from html import unescape
from pathlib import Path
from zipfile import ZipFile

import pytest

from agentic_dt.graph import replay
from agentic_dt.schemas import HumanFrame, RunManifest
from agentic_dt.workflow import run_exercise

pytest.importorskip("flask", reason="Install extensions/web/requirements.txt")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
web = importlib.import_module("extensions.web.app")
work_once = importlib.import_module("extensions.web.worker").work_once


@pytest.fixture
def web_app(project, tmp_path, monkeypatch, request):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return web.create_app(
        {
            "TESTING": True,
            "PROJECT_CONFIG": project,
            "DATA_ROOT": tmp_path / "web-data",
            "SECRET_KEY": "fictional-offline-test-key",
            "ACCESS_PASSWORD": "",
            "RUN_BUDGET_USD": "0",
            "PROJECT_BUDGET_USD": "0.50",
            "USER_BUDGET_USD": None,
            "TOTAL_BUDGET_USD": "5.00",
            "AUTH_MODE": "local",
            "LIVE_ENABLED": None,
            **getattr(request, "param", {}),
        }
    )


@pytest.fixture
def browser(web_app):
    client = web_app.test_client()
    assert client.get("/").status_code == 200
    return client


def post(browser, url, data=None, **kwargs):
    """Submit a real form with the CSRF token issued to this browser."""
    with browser.session_transaction() as state:
        csrf = state["csrf"]
        project_id = state.get("workspace_id", "")
    return browser.post(
        url, data={"csrf": csrf, "project_id": project_id, **(data or {})}, **kwargs
    )


@pytest.fixture
def workspace(browser, web_app, request):
    response = post(
        browser,
        "/create",
        {
            "name": "FICTIONAL workshop inquiry",
            "author": "fictional-tester",
            "brief_text": getattr(
                request, "param", "FICTIONAL: understand low workshop attendance."
            ),
        },
    )
    assert response.status_code == 302
    with browser.session_transaction() as state:
        return Path(web_app.config["DATA_ROOT"]) / "projects" / state["workspace_id"]


@pytest.fixture
def frame_form():
    return {
        "exercise": "frame_challenge",
        "framing": "FICTIONAL-HUMAN-FRAME-NEVER-FOR-THE-MODEL",
        "observations": "The brief reports low attendance.",
        "assumptions": "Timing could explain attendance.",
        "alternative_frame": "Investigate whether sessions are accessible.",
        "open_questions": "What distinguishes timing from awareness?",
    }


@pytest.fixture
def prepared(browser, workspace, frame_form):
    response = post(browser, "/project/prepare", frame_form)
    assert response.status_code == 302
    return response.headers["Location"]


@pytest.fixture
def offline_client(workspace, prepared, fake_client_type):
    directory = workspace / "runs" / prepared.rsplit("/", 1)[1]
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    source = manifest.sources[0]
    client = fake_client_type(
        [
            {
                "role": "analyst",
                "exercise_id": "frame_challenge",
                "claims": [
                    {
                        "local_id": f"c{index}",
                        "statement": (
                            f"{deliverable}: the brief reports low attendance."
                        ),
                        "claim_type": "observation",
                        "deliverable": deliverable,
                        "evidence_refs": [source.source_id],
                        "citations": [
                            {"source_id": source.source_id, "passage_id": "p1"}
                        ],
                        "derived_from": [],
                        "confidence": 0.8,
                        "public_reasoning_summary": "An attributed brief statement.",
                        "open_questions": ["What explains attendance?"],
                    }
                    for index, deliverable in enumerate(manifest.deliverables, start=1)
                ],
            }
        ]
    )
    return directory, manifest, client


@pytest.fixture
def completed_web(browser, workspace, prepared, offline_client):
    directory, manifest, client = offline_client
    run_exercise(
        workspace / "config/project.yaml",
        "frame_challenge",
        directory,
        [],
        False,
        True,
        web.Decimal("0.01"),
        client=client,
        human_frame_path=Path(manifest.human_frame.source_path),
    )
    assert browser.get(prepared).status_code == 200
    return directory, manifest


def test_uploads_are_private_explicit_escaped_and_separate(
    browser, workspace, web_app, project
):
    before = project.read_bytes()
    response = post(
        browser,
        "/project/upload",
        {"evidence": (io.BytesIO(b"<script>untrusted</script>"), "../../notes.md")},
    )
    assert response.status_code == 302
    index = json.loads((workspace / "project.json").read_text())
    document = index["uploads"][0]
    assert document["name"] == "notes.md"
    assert (workspace / "uploads" / document["file"]).is_file()
    response = browser.get("/project")
    assert b"&lt;script&gt;untrusted&lt;/script&gt;" in response.data
    assert b"<script>" not in response.data
    assert project.read_bytes() == before
    assert not (project.parent.parent / "outputs").exists()
    other = web_app.test_client()
    assert other.get("/project").status_code == 404
    assert not (workspace / "ledger/events.jsonl").exists()


@pytest.mark.parametrize(
    "web_app", [{"PROJECT_CONFIG": web.ROOT / "config/project.yaml"}], indirect=True
)
def test_exercise_selection_and_fallback_prepare_only_the_selected_exercise(
    browser, workspace, frame_form, tmp_path
):
    uploaded = post(
        browser,
        "/project/upload",
        {
            "exercise": "interviews",
            "evidence": (io.BytesIO(b"FICTIONAL participant notes."), "notes.md"),
        },
    )
    assert uploaded.status_code == 302
    assert uploaded.headers["Location"] == "/project?exercise=interviews#exercise"
    original_index = (workspace / "project.json").read_bytes()
    response = browser.get("/project?exercise=interviews")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    expected = (web.ROOT / "exercises/11_interviews.md").read_text()
    displayed = re.search(
        r'<details id="exercise-instructions">.*?<pre>(.*?)</pre>', text, re.S
    )[1]
    assert unescape(displayed) == expected
    assert '<option value="interviews" selected>' in text
    assert (
        'id="prepared-exercise" type="hidden" name="exercise" value="interviews"'
        in text
    )
    assert text.count('<template id="instructions-') == 13
    assert '<button id="choose-exercise" type="submit">' in text
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert (workspace / "project.json").read_bytes() == original_index
    assert not (workspace / "ledger/events.jsonl").exists()

    preview = tmp_path / "browser-preview"
    (preview / "static").mkdir(parents=True)
    (preview / "index.html").write_bytes(response.data)
    for filename in ("readability.css", "exercise-selector.js"):
        asset = browser.get(f"/static/{filename}")
        assert asset.status_code == 200
        (preview / "static" / filename).write_bytes(asset.data)
    print(f"Fictional exercise selector preview: {preview}")

    response = post(
        browser, "/project/prepare", {**frame_form, "exercise": "interviews"}
    )
    assert response.status_code == 302
    directory = workspace / "runs" / response.headers["Location"].rsplit("/", 1)[1]
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    assert manifest.exercise_id == "interviews"
    assert manifest.exercise_source.content == expected
    assert not (directory / "analyst_response.json").exists()


@pytest.mark.parametrize(
    "web_app", [{"PROJECT_CONFIG": web.ROOT / "config/project.yaml"}], indirect=True
)
@pytest.mark.parametrize(
    "exercise_id",
    [
        item["id"]
        for item in web.yaml.safe_load((web.ROOT / "config/project.yaml").read_text())[
            "exercises"
        ]
    ],
)
def test_each_exercise_has_specific_prompts_and_freezes_private_answers(
    browser, workspace, exercise_id
):
    catalog = web.yaml.safe_load(
        (web.ROOT / "extensions/web/interpretations.yaml").read_text()
    )
    prompts = catalog[exercise_id]
    assert set(prompts) == set(HumanFrame.model_fields) - {"author_id", "exercise_id"}
    assert (
        len(
            {
                tuple(item["label"] for item in group.values())
                for group in catalog.values()
            }
        )
        == 13
    )
    response = browser.get(f"/project?exercise={exercise_id}")
    assert response.status_code == 200
    active = unescape(
        re.search(
            r'<div id="interpretation-fields">(.*?)</div>',
            response.get_data(as_text=True),
            re.S,
        )[1]
    )
    assert len(re.findall(r"<textarea\b", active)) == 5
    for name, prompt in prompts.items():
        assert prompt["label"] in active
        assert prompt["hint"] in active
        assert f'name="{name}"' in active
        assert f'aria-describedby="hint-{name}" required' in active
    if exercise_id != "frame_challenge":
        assert catalog["frame_challenge"]["framing"]["label"] not in active

    answers = {name: f"FICTIONAL-PRIVATE-{exercise_id}-{name}" for name in prompts}
    saved = post(browser, "/project/prepare", {"exercise": exercise_id, **answers})
    assert saved.status_code == 302
    directory = workspace / "runs" / saved.headers["Location"].rsplit("/", 1)[1]
    manifest = RunManifest.model_validate_json(
        (directory / "input_manifest.json").read_bytes()
    )
    frozen = web.yaml.safe_load(manifest.human_frame.content)
    assert manifest.exercise_id == frozen["exercise_id"] == exercise_id
    for name, answer in answers.items():
        assert frozen[name] == (
            [answer]
            if name in {"observations", "assumptions", "open_questions"}
            else answer
        )
        assert answer not in (directory / "analyst_request.json").read_text()
    assert not (directory / "analyst_response.json").exists()
    assert not (workspace / "ledger/events.jsonl").exists()


def test_upload_with_unknown_exercise_does_not_save_files(browser, workspace):
    before = (workspace / "project.json").read_bytes()
    response = post(
        browser,
        "/project/upload",
        {
            "exercise": "unknown-exercise",
            "evidence": (io.BytesIO(b"FICTIONAL participant notes."), "notes.md"),
        },
    )
    assert response.status_code == 422
    assert (workspace / "project.json").read_bytes() == before
    assert list((workspace / "uploads").iterdir()) == []


def test_project_order_keeps_saved_runs_and_export_after_reviewed_findings(
    browser, workspace, prepared, review_form
):
    assert post(browser, prepared + "/review", review_form).status_code == 302
    ledger = workspace / "ledger/events.jsonl"
    before = ledger.read_bytes()
    text = browser.get("/project").get_data(as_text=True)
    sections = [
        "1. Choose an exercise",
        "2. Add evidence",
        "Your independent interpretation:",
        "Evidence for this exercise</legend>",
        "Reviewed findings to include</legend>",
        "Save interpretation and preview request",
        "3. Continue saved runs",
        "4. Export reviewed research",
    ]
    positions = [text.index(section) for section in sections]
    assert positions == sorted(positions)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    ("content", "name"),
    [(b"%PDF", "notes.pdf"), (b"\xff", "notes.txt"), (b"", "notes.md")],
)
def test_unsupported_uploads_do_not_change_the_index(browser, workspace, content, name):
    response = post(
        browser, "/project/upload", {"evidence": (io.BytesIO(content), name)}
    )
    assert response.status_code == 422
    assert json.loads((workspace / "project.json").read_text())["uploads"] == []


def test_preview_withholds_independent_frame_and_makes_no_calls(
    browser, workspace, prepared
):
    directory = workspace / "runs" / prepared.rsplit("/", 1)[1]
    wire = (directory / "analyst_request.json").read_text()
    assert "FICTIONAL-HUMAN-FRAME-NEVER-FOR-THE-MODEL" not in wire
    assert not (directory / "analyst_response.json").exists()
    assert not (workspace / "ledger/events.jsonl").exists()
    assert b"Live AI calls are disabled" in browser.get(prepared).data
    assert post(browser, prepared, {"authorize": "yes"}).status_code == 403
    assert not (directory / "analyst_response.json").exists()


def test_csrf_and_upload_size_are_enforced(browser, workspace):
    assert browser.post("/project/upload", data={}).status_code == 400
    response = post(
        browser,
        "/project/upload",
        {"evidence": (io.BytesIO(b"x" * 30_001), "large.txt")},
    )
    assert response.status_code == 422
    assert b"30,000 byte limit" in response.data
    assert json.loads((workspace / "project.json").read_text())["uploads"] == []
    response = post(
        browser,
        "/project/upload",
        {"evidence": (io.BytesIO(b"x" * 1_000_001), "too-large.txt")},
    )
    assert response.status_code == 413


def test_invitation_password_and_private_headers(web_app):
    web_app.config["ACCESS_PASSWORD"] = "fictional-invitation"
    client = web_app.test_client()
    assert client.get("/").headers["Location"] == "/login"
    response = client.get("/login")
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert post(client, "/login", {"password": "wrong"}).status_code == 403
    assert (
        post(client, "/login", {"password": "fictional-invitation"}).status_code == 302
    )
    assert client.get("/").status_code == 200


def test_review_and_export_use_the_real_append_only_workflow(
    browser, workspace, prepared, completed_web, web_app
):
    directory, manifest = completed_web
    review_url = prepared + "/review"
    assert browser.get(review_url).status_code == 200
    response = post(
        browser,
        review_url,
        {
            "decision_0": "accept",
            "status_0": "supported",
            "reason_0": "The brief explicitly reports this attributed observation.",
            "decision_1": "accept",
            "status_1": "proposed",
            "reason_1": "Retain the attributed report for investigation.",
            "revised_frame": "Investigate the causes of low attendance.",
            "disagreement": "The brief does not establish a cause.",
            "assumptions_reconsidered": "Low awareness may not be the cause.",
            "next_research_question": "Ask participants what affects access.",
            "revision_trigger": "Participant accounts distinguish causes.",
            "reflection_evidence": manifest.sources[0].source_id,
        },
    )
    assert response.status_code == 302
    ledger = workspace / "ledger/events.jsonl"
    before = ledger.read_bytes()
    assert len(replay(ledger).reportable_claims()) == 1
    assert (directory / "review.receipt.json").exists()
    assert post(browser, review_url).status_code == 302
    assert ledger.read_bytes() == before
    response = post(browser, "/project/export")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.data)) as archive:
        assert set(archive.namelist()) == {
            "design_research_brief.md",
            "synthesis_index.json",
            "ledger/events.jsonl",
        }
        assert archive.read("ledger/events.jsonl") == before
        assert b"low attendance" in archive.read("design_research_brief.md")
    original_manifest = (directory / "input_manifest.json").read_bytes()
    response = browser.get("/project/restart")
    assert response.status_code == 200
    assert b"FICTIONAL: understand low workshop attendance." in response.data
    assert (
        post(
            browser,
            "/create",
            {
                "restart_from": workspace.name,
                "name": "Revised fictional inquiry",
                "author": "fictional-tester",
                "brief_text": "FICTIONAL: investigate access for shift workers.",
            },
        ).status_code
        == 302
    )
    with browser.session_transaction() as state:
        new_id = state["workspace_id"]
        assert "workspace_ids" not in state
        owner = state["user_id"]
    with web_app.extensions["web_store"].connection() as db:
        assert {
            row["id"]
            for row in db.execute("SELECT id FROM projects WHERE owner_id=?", (owner,))
        } == {workspace.name, new_id}
    fresh = Path(web_app.config["DATA_ROOT"]) / "projects" / new_id
    index = json.loads((fresh / "project.json").read_text())
    assert index["uploads"] == []
    assert index["runs"] == {}
    assert "shift workers" in (fresh / "brief.md").read_text()
    assert not (fresh / "ledger/events.jsonl").exists()
    assert ledger.read_bytes() == before
    assert (directory / "input_manifest.json").read_bytes() == original_manifest
    assert b"Revised fictional inquiry" in browser.get("/projects").data
    assert (
        post(browser, "/projects", {"workspace_id": workspace.name}).status_code == 302
    )
    assert browser.get(prepared).status_code == 200
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    "workspace",
    [
        "FICTIONAL interview: <script>untrusted</script> "
        + "Interview context and qualifications. " * 40
        + "END_OF_FULL_INTERVIEW"
    ],
    indirect=True,
)
def test_response_wraps_and_indexes_repeated_passages(
    browser, workspace, prepared, completed_web, tmp_path
):
    directory, _ = completed_web
    before = (directory / "analyst_response.json").read_bytes()
    response = browser.get(prepared)
    text = response.get_data(as_text=True)
    assert "# Inquiry comparison" not in text
    assert text.count('id="passage-1"') == 1
    assert text.count('href="#passage-1"') == 2
    assert 'id="passage-2"' not in text
    excerpt = re.search(r'<section id="passage-1">(.*?)</section>', text, re.S)[1]
    assert "END_OF_FULL_INTERVIEW" not in excerpt
    assert "END_OF_FULL_INTERVIEW" in text
    assert "&lt;script&gt;untrusted&lt;/script&gt;" in excerpt
    assert "<script>" not in text
    review = browser.get(prepared + "/review").get_data(as_text=True)
    assert review.count('id="passage-1"') == 1
    assert review.count('href="#passage-1"') == 2
    assert (directory / "analyst_response.json").read_bytes() == before
    css = browser.get("/static/readability.css")
    assert css.status_code == 200
    assert b"white-space: pre-wrap" in css.data
    assert "style-src 'self'" in response.headers["Content-Security-Policy"]
    preview = tmp_path / "browser-preview"
    (preview / "static").mkdir(parents=True)
    (preview / "index.html").write_bytes(response.data)
    (preview / "static/readability.css").write_bytes(css.data)
    print(f"Fictional browser preview: {preview}")


def test_missing_reflection_cannot_apply_a_review(
    browser, workspace, prepared, completed_web
):
    response = post(
        browser,
        prepared + "/review",
        {
            "decision_0": "accept",
            "status_0": "proposed",
            "reason_0": "Keep this interpretation for investigation.",
            "decision_1": "accept",
            "status_1": "proposed",
            "reason_1": "Keep the second interpretation for investigation.",
            "revised_frame": "",
            "disagreement": "",
            "assumptions_reconsidered": "",
            "next_research_question": "",
            "revision_trigger": "",
        },
    )
    assert response.status_code == 422
    assert not (workspace / "ledger/events.jsonl").exists()


@pytest.fixture
def review_form(completed_web):
    _, manifest = completed_web
    return {
        "decision_0": "keep",
        "status_0": "supported",
        "reason_0": "This is an attributed report, limited to the supplied brief.",
        "decision_1": "keep",
        "status_1": "proposed",
        "reason_1": "Keep this working interpretation for investigation.",
        "revised_frame": "Investigate the causes of low attendance.",
        "disagreement": "The supplied brief does not establish a cause.",
        "assumptions_reconsidered": "Low awareness may not be the cause.",
        "next_research_question": "Which participant roles are missing?",
        "revision_trigger": "A contrasting participant account changes the scope.",
        "reflection_evidence": manifest.sources[0].source_id,
    }


@pytest.mark.parametrize(
    ("action", "original_decision", "human_revision"),
    [
        ("keep", "accepted", False),
        ("revise", "rejected", True),
        ("exclude", "rejected", False),
        ("accept", "rejected", True),  # A form opened before the UI change.
    ],
)
def test_review_choices_preserve_core_decisions_and_human_authorship(
    browser,
    workspace,
    prepared,
    completed_web,
    review_form,
    action,
    original_decision,
    human_revision,
):
    directory, manifest = completed_web
    review_form.update(
        {
            "decision_0": action,
            "revision_0": "The fictional sponsor reports low workshop attendance.",
            "confidence_0": "0.65",
        }
    )
    assert post(browser, prepared + "/review", review_form).status_code == 302
    ledger = workspace / "ledger/events.jsonl"
    state = replay(ledger)
    original_id = f"{manifest.run_id}:c1"
    assert state.reviews[original_id] == original_decision
    human_claims = [
        claim for claim in state.claims.values() if claim.agent_id == "human"
    ]
    assert len(human_claims) == int(human_revision)
    if human_revision:
        claim = human_claims[0]
        assert claim.author_id == "fictional-tester"
        assert claim.statement == review_form["revision_0"]
        assert claim.confidence == 0.65
        assert state.reviews[claim.claim_id] == "accepted"
    if action == "exclude":
        assert state.statuses[original_id] == "proposed"
    before = ledger.read_bytes()
    review_form["decision_0"] = "exclude"
    assert post(browser, prepared + "/review", review_form).status_code == 302
    assert ledger.read_bytes() == before
    assert (directory / "review.receipt.json").exists()
    page = browser.get(prepared + "/review").get_data(as_text=True)
    assert "disabled" in page
    if human_revision:
        assert 'value="revise" selected' in page


@pytest.mark.parametrize("missing", ["revision_0", "confidence_0"])
def test_revise_requires_wording_and_human_confidence_before_saving(
    browser, workspace, prepared, completed_web, review_form, missing
):
    directory, _ = completed_web
    worksheet = directory / "review.yaml"
    before = worksheet.read_bytes()
    review_form.update(
        {
            "decision_0": "revise",
            "revision_0": "The brief reports low attendance.",
            "confidence_0": "0.65",
        }
    )
    review_form[missing] = ""
    response = post(browser, prepared + "/review", review_form)
    assert response.status_code == 422
    assert b"Claim 1: Revise requires" in response.data
    assert worksheet.read_bytes() == before
    assert not (workspace / "ledger/events.jsonl").exists()


def test_excluded_claim_can_retain_a_contested_evidence_judgment(
    browser, workspace, prepared, completed_web, review_form
):
    _, manifest = completed_web
    review_form.update({"decision_0": "exclude", "status_0": "contested"})
    assert post(browser, prepared + "/review", review_form).status_code == 302
    state = replay(workspace / "ledger/events.jsonl")
    claim_id = f"{manifest.run_id}:c1"
    assert state.reviews[claim_id] == "rejected"
    assert state.statuses[claim_id] == "contested"


def test_review_separates_current_evidence_from_future_questions(
    browser, prepared, completed_web, tmp_path
):
    response = browser.get(prepared + "/review")
    text = response.get_data(as_text=True)
    assert "accurate, appropriately scoped interpretation" in text
    assert 'value="keep"' in text and 'value="revise"' in text
    assert 'value="exclude"' in text
    assert 'value="proposed" selected>Tentative' in text
    assert re.search(
        r"<details><summary>Model details</summary>.*?Model confidence.*?</details>",
        text,
    )
    assert text.index("What explains attendance?") > text.index(
        "<h3>Next investigation</h3>"
    )
    assert text.count("What explains attendance?") == 1
    preview = tmp_path / "browser-preview"
    (preview / "static").mkdir(parents=True)
    (preview / "index.html").write_bytes(response.data)
    (preview / "static/readability.css").write_bytes(
        browser.get("/static/readability.css").data
    )
    print(f"Fictional review preview: {preview}")


@pytest.mark.parametrize(
    "web_app",
    [{"RUN_BUDGET_USD": "0.01", "PROJECT_BUDGET_USD": "0.0022"}],
    indirect=True,
)
def test_live_authorization_and_project_budget_use_core_reservations(
    browser, prepared, offline_client, frame_form, monkeypatch, workspace, web_app
):
    directory, _, client = offline_client
    monkeypatch.setenv("OPENAI_API_KEY", "fictional-offline-sdk-key")
    workflow = importlib.import_module("agentic_dt.workflow")
    monkeypatch.setattr(workflow, "OpenAI", lambda **_kwargs: nullcontext(client))
    response = browser.get("/project")
    assert b"Real AI requests are enabled" in response.data
    assert b"fictional-offline-sdk-key" not in response.data
    assert post(browser, prepared).status_code == 400
    assert client.responses.calls == 0
    assert post(browser, prepared, {"authorize": "yes"}).status_code == 302
    assert client.responses.calls == 0
    assert b"analysis is queued" in browser.get(prepared).data
    assert work_once(web_app.extensions["web_store"])
    assert client.responses.calls == 1
    assert web._reserved(directory) == web.Decimal("0.0022")
    second = post(browser, "/project/prepare", frame_form).headers["Location"]
    assert post(browser, second, {"authorize": "yes"}).status_code == 400
    assert (
        post(
            browser,
            "/create",
            {
                "restart_from": workspace.name,
                "name": "Restarted fictional inquiry",
                "author": "fictional-tester",
                "brief_text": "FICTIONAL: a revised challenge brief.",
            },
        ).status_code
        == 302
    )
    restarted = post(browser, "/project/prepare", frame_form).headers["Location"]
    assert post(browser, restarted, {"authorize": "yes"}).status_code == 400
    assert client.responses.calls == 1


def test_blank_restart_migrates_existing_sessions_and_rejects_stale_forms(
    browser, workspace
):
    with browser.session_transaction() as state:
        state["workspace_ids"] = [workspace.name]
    response = browser.get("/project/restart?blank=1")
    assert response.status_code == 200
    assert b"FICTIONAL: understand low workshop attendance." not in response.data
    with browser.session_transaction() as state:
        assert "workspace_ids" not in state
    fields = {
        "restart_from": workspace.name,
        "name": "Fresh fictional project",
        "author": "fictional-tester",
        "brief_text": "",
    }
    assert post(browser, "/create", fields).status_code == 422
    with browser.session_transaction() as state:
        assert state["workspace_id"] == workspace.name
    fields["brief_text"] = "FICTIONAL: a new challenge."
    assert post(browser, "/create", fields).status_code == 302
    assert post(browser, "/create", fields).status_code == 409


@pytest.mark.parametrize("web_app", [{"RUN_BUDGET_USD": "0.01"}], indirect=True)
@pytest.mark.parametrize("run_state", ["failed", "running"])
def test_retry_form_requires_one_authorization_and_submits_the_retry(
    browser, prepared, offline_client, monkeypatch, run_state, web_app
):
    directory, _, client = offline_client
    status_path = directory / "status.json"
    status = json.loads(status_path.read_text())
    status["state"] = run_state
    status_path.write_text(json.dumps(status))
    monkeypatch.setenv("OPENAI_API_KEY", "fictional-offline-sdk-key")
    workflow = importlib.import_module("agentic_dt.workflow")
    monkeypatch.setattr(workflow, "OpenAI", lambda **_kwargs: nullcontext(client))
    response = browser.get(prepared)
    inputs = re.findall(r"<input\b[^>]*>", response.get_data(as_text=True))
    checkboxes = [tag for tag in inputs if 'type="checkbox"' in tag]
    assert len(checkboxes) == 1
    assert 'name="authorize"' in checkboxes[0]
    assert "required" in checkboxes[0]
    assert any(
        'type="hidden"' in tag and 'name="retry_failed"' in tag and 'value="yes"' in tag
        for tag in inputs
    )
    assert post(browser, prepared, {"retry_failed": "yes"}).status_code == 400
    assert client.responses.calls == 0
    assert (
        post(browser, prepared, {"authorize": "yes", "retry_failed": "yes"}).status_code
        == 302
    )
    assert client.responses.calls == 0
    assert work_once(web_app.extensions["web_store"])
    assert client.responses.calls == 1
    assert json.loads(status_path.read_text())["state"] == "awaiting_review"


def test_saved_projects_cannot_be_opened_by_another_browser(
    browser, workspace, web_app
):
    other = web_app.test_client()
    assert other.get("/").status_code == 200
    assert (
        post(
            other,
            "/create",
            {
                "name": "Other fictional tester's project",
                "author": "another-fictional-tester",
                "brief_text": "FICTIONAL: unrelated challenge.",
            },
        ).status_code
        == 302
    )
    assert post(other, "/projects", {"workspace_id": workspace.name}).status_code == 404
    assert b"FICTIONAL workshop inquiry" not in other.get("/projects").data
    assert b"FICTIONAL workshop inquiry" not in other.get("/project").data


def test_project_selector_and_list_reopen_current_and_other_projects(
    browser, workspace, prepared
):
    assert (
        post(
            browser,
            "/project/draft",
            {"exercise": "frame_challenge", "draft_version": "0", "framing": "FIRST"},
        ).status_code
        == 302
    )
    assert (
        post(
            browser,
            "/create",
            {
                "restart_from": workspace.name,
                "name": "FICTIONAL second <project>",
                "author": "fictional-tester",
                "brief_text": "FICTIONAL: a second challenge.",
            },
        ).status_code
        == 302
    )
    with browser.session_transaction() as state:
        second_id = state["workspace_id"]
    assert (
        post(
            browser,
            "/project/draft",
            {"exercise": "frame_challenge", "draft_version": "0", "framing": "SECOND"},
        ).status_code
        == 302
    )
    for path in ("/", "/projects", "/project"):
        page = browser.get(path).get_data(as_text=True)
        selector = re.search(r'<select name="workspace_id".*?</select>', page, re.S)[0]
        assert f'value="{workspace.name}"' in selector
        assert f'value="{second_id}" selected' in selector
        assert "FICTIONAL second &lt;project&gt;" in selector
        assert ">Your project</a>" not in page
    page = browser.get("/projects").get_data(as_text=True)
    # The current row needs a real form too; otherwise the list cannot reopen it.
    assert f'name="workspace_id" value="{second_id}"' in page
    assert post(browser, "/projects", {"workspace_id": second_id}).status_code == 302
    assert b">SECOND</textarea>" in browser.get("/project").data
    assert (
        post(browser, "/projects", {"workspace_id": workspace.name}).status_code == 302
    )
    assert b">FIRST</textarea>" in browser.get("/project").data
    run_page = browser.get(prepared).get_data(as_text=True)
    assert f'value="{second_id}"' in run_page
    assert post(browser, "/projects", {"workspace_id": second_id}).status_code == 302
    assert browser.get(prepared).status_code == 404
    assert b">SECOND</textarea>" in browser.get("/project").data


def test_website_no_longer_exposes_worked_example(browser, workspace, prepared):
    for path in ("/", "/projects", "/project", prepared):
        page = browser.get(path).get_data(as_text=True)
        assert "worked example" not in page.lower()
        assert 'action="/example"' not in page
    assert browser.get("/example").status_code == 404
    assert post(browser, "/example").status_code == 404
    assert not (workspace.parent.parent / "examples").exists()


def test_browser_session_survives_app_restart(web_app, browser, workspace):
    settings = {
        key: web_app.config[key]
        for key in (
            "DATA_ROOT",
            "PROJECT_CONFIG",
            "SECRET_KEY",
            "ACCESS_PASSWORD",
            "RUN_BUDGET_USD",
            "PROJECT_BUDGET_USD",
            "TESTING",
        )
    }
    restarted = web.create_app(settings).test_client()
    name = web_app.config["SESSION_COOKIE_NAME"]
    restarted.set_cookie(name, browser.get_cookie(name).value)
    response = restarted.get("/project")
    assert response.status_code == 200
    assert b"FICTIONAL workshop inquiry" in response.data
