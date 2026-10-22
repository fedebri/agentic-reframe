"""Exercise a loopback Workers preview using fictional inputs and optional stub AI."""

import argparse
import html
import http.cookiejar
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent


class Browser:
    """A separate browser identity with real cookies, forms, and HTTP requests."""

    def __init__(self, base: str, *, resume: bool = False):
        self.base = base
        self.cookies = http.cookiejar.LWPCookieJar(str(HERE / ".smoke-cookies.local"))
        if resume:
            self.cookies.load(ignore_discard=True, ignore_expires=True)
        self.http = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def request(self, path, data=None, *, content_type=None):
        headers = {"Content-Type": content_type} if content_type else {}
        payload = (
            urllib.parse.urlencode(data, doseq=True).encode()
            if isinstance(data, dict)
            else data
        )
        request = urllib.request.Request(
            self.base + path, data=payload, headers=headers
        )
        try:
            with self.http.open(request, timeout=30) as response:
                body = response.read()
                return response.status, response.url.removeprefix(self.base), body
        except urllib.error.HTTPError as error:
            return error.code, error.url.removeprefix(self.base), error.read()

    def form(self, path, fields, page):
        values = {
            match[0]: html.unescape(match[1])
            for match in re.findall(
                r'name="(csrf|project_id|restart_from)" value="([^"]*)"', page.decode()
            )
        }
        return self.request(path, {**values, **fields})


def main():
    """Run against the local environment; never accept a public target or real key."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8790")
    parser.add_argument(
        "--analysis", action="store_true", help="Use ONLY the local fixture runner"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Verify state after restarting Wrangler"
    )
    arguments = parser.parse_args()
    parsed = urllib.parse.urlsplit(arguments.url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Smoke tests only accept an HTTP loopback Workers emulator.")
    browser = Browser(arguments.url, resume=arguments.resume)
    if arguments.resume:
        saved = json.loads((HERE / ".smoke-expectations.local").read_text())
        status, _, page = browser.request("/projects")
        assert status == 200 and saved["name"].encode() in page
        status, _, page = browser.request("/project")
        assert status == 200 and saved["draft"].encode() in page
        if saved.get("run"):
            status, _, page = browser.request(saved["run"])
            assert status == 200 and b"FICTIONAL Cloudflare smoke-test finding" in page
        print("PASS: projects, drafts, and results survive a Workers runtime restart.")
        return
    status, _, page = browser.request("/")
    assert status == 200, page.decode()[:1000]
    name = "FICTIONAL Cloudflare test " + uuid4().hex[:8]
    status, _, page = browser.form(
        "/create",
        {
            "name": name,
            "author": "Fictional tester",
            "brief_text": "FICTIONAL brief: investigate workshop participation. "
            + ("FICTIONAL-SIMULATE-429" if arguments.analysis else ""),
        },
        page,
    )
    assert status == 200 and name.encode() in page, page.decode()[:1000]
    project_id = re.search(rb'name="project_id" value="([^"]+)"', page)[1].decode()
    draft = "FICTIONAL-HUMAN-ONLY: investigate timing and access."
    status, _, page = browser.form(
        "/project/draft",
        {"exercise": "frame_challenge", "draft_version": "0", "framing": draft},
        page,
    )
    assert status == 200 and draft.encode() in page, page.decode()[:1000]
    # Submit a real multipart upload without driving an OS file picker.
    boundary = "fictional-cloudflare-boundary"
    csrf = re.search(rb'name="csrf" value="([^"]+)"', page)[1].decode()
    upload = io.BytesIO()
    for field, value in (
        ("csrf", csrf),
        ("project_id", project_id),
        ("exercise", "frame_challenge"),
    ):
        upload.write(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"'
                f"\r\n\r\n{value}\r\n"
            ).encode()
        )
    upload.write(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            'name="evidence"; filename="fictional-note.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
            "FICTIONAL interview note: one person could attend only in the evening."
            f"\r\n--{boundary}--\r\n"
        ).encode()
    )
    status, _, page = browser.request(
        "/project/upload",
        upload.getvalue(),
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    assert status == 200 and b"fictional-note.md" in page, page.decode()[:1000]
    evidence_id = re.search(rb'name="evidence" value="([^"]+)"', page)[1].decode()
    independent = Browser(arguments.url)
    assert independent.request("/")[0] == 200
    other_page = independent.request("/")[2]
    assert (
        independent.form("/projects", {"workspace_id": project_id}, other_page)[0]
        == 404
    )
    status, run, run_page = browser.form(
        "/project/prepare",
        {
            "exercise": "frame_challenge",
            "draft_version": re.search(rb'name="draft_version" value="(\d+)"', page)[
                1
            ].decode(),
            "framing": draft,
            "observations": "FICTIONAL note names one person's timing constraint.",
            "assumptions": "Timing may matter for other participants.",
            "alternative_frame": "Recruitment channels may explain who participates.",
            "open_questions": "Which perspectives are missing?",
            "evidence": evidence_id,
            "critic": "yes",
        },
        page,
    )
    assert status == 200 and b"prepared" in run_page, run_page.decode()[:1000]
    assert independent.request(run)[0] == 404
    saved = {"name": name, "draft": draft}
    if arguments.analysis:
        # Refuse to submit unless the configured local binding is the fixture.
        _, _, inventory = browser.request("/cdn-cgi/local/explorer/api/local/workers")
        assert b"agentic-reframe-runner-fixture" in inventory, (
            "Start the fixture Worker first."
        )
        status, _, run_page = browser.form(run, {"authorize": "yes"}, run_page)
        assert status == 200 and (b"queued" in run_page or b"running" in run_page), (
            run_page.decode()[:1000]
        )
        # Native alarms start after one second; save an independent draft mid-call.
        time.sleep(1.5)
        status, _, project_page = browser.request("/project")
        assert status == 200
        saved["draft"] = "FICTIONAL-HUMAN-ONLY: draft saved during analysis."
        status, _, page = browser.form(
            "/project/draft",
            {
                "exercise": "frame_challenge",
                "draft_version": re.search(
                    rb'name="draft_version" value="(\d+)"', project_page
                )[1].decode(),
                "framing": saved["draft"],
            },
            project_page,
        )
        assert status == 200 and saved["draft"].encode() in page
        for _ in range(25):
            status, _, run_page = browser.request(run)
            assert status == 200
            if b"Compare interpretations" in run_page:
                break
            time.sleep(1)
        assert b"FICTIONAL Cloudflare smoke-test finding" in run_page, (
            run_page.decode()[-5000:]
        )
        status, _, review = browser.request(run + "/review")
        assert status == 200
        source = re.search(rb'name="reflection_evidence" value="([^"]+)"', review)[
            1
        ].decode()
        fields = {
            "revised_frame": "FICTIONAL frame: investigate access within this scope.",
            "disagreement": "FICTIONAL generated claims are only a test fixture.",
            "assumptions_reconsidered": "FICTIONAL timing barriers may not be shared.",
            "next_research_question": "Whose missing perspective should we explore?",
            "revision_trigger": "FICTIONAL contrary evidence would change this frame.",
            "reflection_evidence": source,
        }
        for index in range(len(re.findall(rb'name="decision_\d+"', review))):
            fields.update(
                {
                    f"decision_{index}": "keep",
                    f"status_{index}": "proposed",
                    f"reason_{index}": "FICTIONAL test; kept as a tentative claim.",
                }
            )
        status, _, applied = browser.form(run + "/review", fields, review)
        assert status == 200 and b"View saved review" in applied, applied.decode()[
            -2500:
        ]
        assert b"read-only" in browser.request(run + "/review")[2]
        status, _, page = browser.request("/project")
        assert status == 200 and saved["draft"].encode() in page
        assert b"Reviewed" in page
        status, _, page = browser.form(
            "/project/navigate",
            {
                "exercise": "frame_challenge",
                "draft_version": re.search(
                    rb'name="draft_version" value="(\d+)"', page
                )[1].decode(),
                "framing": saved["draft"],
                "target_exercise": "align_impact_goals",
            },
            page,
        )
        assert status == 200 and b'<option value="align_impact_goals" selected>' in page
        status, _, page = browser.form(
            "/project/navigate",
            {
                "exercise": "align_impact_goals",
                "draft_version": "0",
                "framing": "FICTIONAL goal draft",
                "navigation": "skip",
                "skip_reason": "FICTIONAL awaiting more perspectives",
            },
            page,
        )
        assert (
            status == 200
            and b'<option value="align_participatory_approach" selected>' in page
        )
        assert b"1 skipped" in page and b"FICTIONAL awaiting more perspectives" in page
        status, _, page = browser.request("/project?exercise=frame_challenge")
        assert status == 200 and saved["draft"].encode() in page
        saved["run"] = run
    browser.cookies.save(ignore_discard=True, ignore_expires=True)
    (HERE / ".smoke-expectations.local").write_text(json.dumps(saved))
    print(
        "PASS: private project, partial draft, upload, frozen run, browser isolation."
    )
    if arguments.analysis:
        print(
            "PASS: alarm, private service, SDK with stub provider, critic, "
            "concurrent draft save, human review, navigation and skips."
        )
    print("Restart Wrangler, then run this script with --resume to check persistence.")


if __name__ == "__main__":
    main()
