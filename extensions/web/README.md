# Optional research website

This is a separate prototype adapter for Agentic Reframe. It imports the existing
Python workflow; the core package, CLI, configuration, prompts, exercises, and
existing outputs do not depend on this extension and are not modified by it.
There is no frontend framework or frontend build step. Selecting an exercise
saves its current draft before loading the new instructions and questions.
Without JavaScript, use **Choose exercise** for the same save-and-open action.
The script also saves changed answers before following page links, uploading
evidence or switching projects. A conflict or connection failure leaves the
edits on screen; unexpected refresh/close prompts about unsaved changes.
**Save draft** remains available explicitly. A small stylesheet keeps text
boxes within the page width. Light typography, a blue wordmark/dot, open spacing,
and fine rules borrow a few elements from the Derver website guidelines. Dense
forms retain a white canvas and dark text.

For a deployment entirely on Cloudflare, use the separate
[Workers adapter and setup guide](../cloudflare/README.md). For an always-on Docker
host behind Cloudflare Access/Tunnel, follow [the Docker deployment guide](DEPLOYMENT.md).
Both use this same repository and the same website/core contracts. A static
Cloudflare Pages upload alone cannot run the research workflow.

## Run locally

From the repository root, with the core project installed in its virtual
environment:

```sh
.venv/bin/python -m pip install -r extensions/web/requirements.txt
.venv/bin/python -m extensions.web.app
```

Start the background worker in a second terminal at the same repository root,
using the same `WEB_DATA_ROOT` if you changed it:

```sh
.venv/bin/python -m extensions.web.worker
```

Open <http://127.0.0.1:8787>. Live model calls are **disabled by default**.
The website focuses on the tester's projects. The fictional tutorial remains
available through the core CLI rather than a worked-example website page.

**My projects** lists all projects owned by the current identity. Every project,
including the current one, has an **Open project** button. A named project selector
in the shared header lets you open another project or return from a run/review to
the current project's exercises. Opening a project resumes its last visited
exercise, including on another device for a signed-in tester.

## Exercise navigation

The project page shows ordered progress, **Previous exercise**, **Next exercise**,
and an expandable **All exercises** overview. Each exercise has its own draft,
evidence/claim selection and numbered attempt history. Moving between exercises
does not start an analysis or mark an exercise reviewed.

- **Skip for now and continue** saves the draft, records an optional reason and
  opens the next unfinished exercise. **Resume this exercise** reverses the skip.
  An active analysis finishes normally; navigate away rather than skipping it.
- A saved human review marks coverage as **Reviewed**. The saved run offers
  **Continue to the next exercise**; at the end it links to the coverage overview.
- **Redo exercise** reopens editable human input for a separate new attempt.
  Previous requests, model responses, reviews and ledger entries remain intact.
  A new paid call still requires request preview and explicit authorization.
- **Retry** on a failed/interrupted run retains that run's frozen inputs. It is
  distinct from redoing an exercise with different input.
- Reviewed exercises with a new draft or unfinished attempt show **Reviewed —
  revision in progress**. Navigation does not supersede earlier accepted claims;
  the existing human review and provenance rules still apply.

The current exercise, skip reasons and revision intent live in the existing
private `project.json` index; drafts retain SQLite version checks. Older projects
derive progress from their saved runs and review receipts. If an old run has no
saved draft, the workspace restores its frozen human answers for editing.
No database or ledger migration is required. Final synthesis/output development
remains separate; the existing report export is retained.

The normal workflow supports:

1. Create a project with a pasted or uploaded challenge brief.
2. Upload and preview `.md` and `.txt` evidence; explicitly select files per run.
3. Answer exercise-specific questions and freeze an independent interpretation,
   withheld from AI. Then select evidence and any reviewed findings to include.
4. Inspect the frozen sources and exact AI request without making a model call.
5. When enabled by the host, authorize a paid call and queue the existing
   analyst and optional critic. A separate worker processes the job; the browser
   can be closed and revisited. Failed calls require an explicit retry.
6. Compare interpretations, decide every claim, and record a revised or defended
   frame, disagreement, reconsidered assumptions, and next investigation.
7. Apply the review through the core's append-only mechanism. Download a ZIP with
   the Markdown report, JSON synthesis index, and ledger history.

Completed responses use HTML headings and paragraphs. Claim citations link to a
shared list of distinct passages, each shown once as a short excerpt. Full
sources remain in expandable sections; saved quotations, comparison artifacts,
and provenance are unchanged. The review form uses the same evidence list.

The review asks whether each claim is an accurate, appropriately scoped reading
of the current sources: **Keep**, **Revise**, or **Exclude**. For kept or revised
wording, reviewers assess support as **Supported**, **Tentative**, or
**Contested**. Support is scoped to the supplied evidence, not a claim of
population representativeness. Excluding a claim removes it from findings;
tentative or contested judgments are retained, while a supported rating is
stored as proposed because only retained claims can be recorded as supported.
Model confidence is under details.
Future research questions appear separately under **Next investigation**; they
do not need to be answered to judge the current claim.

Choosing Revise requires revised wording and the researcher's own confidence.
It uses the core's existing human-revision mechanism: the original is retained
and rejected, and the accepted new hypothesis is attributed to the reviewer.
Kept/excluded claims ignore unused revision fields. Existing saved decisions and
applied reviews retain their schema and history; no model output is rewritten
or automatically split into new claims.

All thirteen configured exercises use the same adapter. New uploads and new
interpretations create new runs; existing frozen inputs are preserved. The
prototype requires an independent interpretation for every exercise.
The project page puts exercise selection first, evidence upload second, then the
independent interpretation, evidence selection, and reviewed findings. Uploading
evidence retains the selected exercise. Its attempt history and export remain below.

`interpretations.yaml` contains web-only question labels and guidance derived from
each canonical exercise Markdown file. For example, resource flow asks for
transfers and timing; five whys asks for a linked causal chain and stopping point;
interviews ask for attributed accounts, mixed perspectives, and sampling limits.
The prompts still capture an interpretation, observations, assumptions, an
alternative, and investigation questions in the existing `HumanFrame` schema.
No core schema, prompt, exercise definition, or historical run is changed.

## Revise a brief or start over

On the project page, choose **Revise the brief and restart** to open a form
pre-filled with the current name, researcher, and brief. Edit the text or upload
a replacement brief, then choose **Create fresh project**. **Start a blank
project** opens the same form with empty fields.

Both actions create a new project with no evidence, runs, prior claims, or
ledger. Earlier project directories, frozen inputs, reviews, and ledger history
are retained unchanged. **My projects** lets the owner reopen them.
Upload and select evidence again in the fresh project. When application spending
caps are enabled, restarting does not replenish the owner's allowance:
reservations from all their projects continue to count. A restart form from a
different active project is rejected, so a stale tab cannot silently replace
the project you are working on.

## Storage and separation

Default runtime storage is `extensions/web/.data/`, ignored by the extension's
own `.gitignore`. Set `WEB_DATA_ROOT` to an absolute persistent directory when
hosting. Keep this directory private and back it up: it holds uploads, project
indexes, configuration copies, run checkpoints, reviews, reports, isolated
append-only ledgers, and the generated session-signing key. Older example files,
if present from an earlier version, are retained.
Repository evidence and the repository's `outputs/v2/` ledger are never used as
web-project storage or automatically assigned as evidence.

SQLite (`web.sqlite3` in the data directory) stores verified users, project
ownership, mutable exercise drafts with conflict detection, durable jobs, local
spending estimates, and explicitly shared brief templates. Core inputs, frozen
runs, and append-only ledgers remain in their existing per-project directories.

`WEB_AUTH_MODE=cloudflare` verifies Access JWTs against the configured team,
audience, signatures, and expiry on every request. A verified issuer/subject owns
the projects, so the same person can resume from another machine. Administrator
emails are explicitly listed in `WEB_ADMIN_EMAILS`. Their separate dashboard
shows the cohort's project summaries, job states, estimated spending, and exports;
publishing a brief requires an explicit confirmation and shares only that brief.

The default `WEB_AUTH_MODE=local` retains browser-owned projects for localhost
development. It provides no cross-browser account recovery and grants no admin
role. The old shared password is only a local demonstration gate. Existing signed
browser histories are registered without scanning directories or rewriting runs.
An explicit linking action can move a local identity's projects to a verified
sign-in on the same installation.

Retain the signing key across restarts. Short per-project file locks preserve
filesystem/ledger writes. Active jobs block research-history mutations in their
own project, while page reads and draft saves remain available. There is one
background worker, guarded by its own process lock. Uploads are bounded,
filenames sanitized, forms CSRF-protected, and source text HTML-escaped.

## GitHub and Cloudflare

Use [DEPLOYMENT.md](DEPLOYMENT.md) to configure Access, email invitations, the
application AUD, a remotely managed tunnel, private settings, persistent storage,
and all three services. Compose keeps the web origin off published host ports and
passes the API key only to the worker. The GitHub workflow validates code and
build boundaries; it does not automatically deploy or require Cloudflare secrets.

## Optional live calls

The key is supplied on the server, following the
[official OpenAI authentication guidance](https://developers.openai.com/api/reference/overview#authentication).
It is never entered into a website form, returned to a browser, or saved in the
project. A Codex/ChatGPT login does not configure this process's environment.

For local testing, enable the web queue in the web terminal:

```sh
export WEB_LIVE_ENABLED=1
export WEB_RUN_BUDGET_USD=0.10
export WEB_USER_BUDGET_USD=0.50
export WEB_TOTAL_BUDGET_USD=5.00
.venv/bin/python -m extensions.web.app
```

Supply the key in the separate worker terminal and start the worker:

```sh
export OPENAI_API_KEY='your-api-key'
.venv/bin/python -m extensions.web.worker
```

The amounts above are example local estimates: at most `$0.10` per run and
`$0.50` shared across one tester's projects, and `$5.00` across the deployment.
Launching either process does not call the API. The project page reports whether live requests are
enabled. Save an interpretation and preview its request, then check the spending
authorization and choose **Run AI analysis** on the saved run page.

By default, the host opts in with `WEB_LIVE_ENABLED=1` and positive caps; a local
web process that already has `OPENAI_API_KEY` retains the previous opt-in behavior when
`WEB_LIVE_ENABLED` is unset. The worker must have its own key environment. The old
`WEB_PROJECT_BUDGET_USD` is a compatibility fallback for the user cap if
`WEB_USER_BUDGET_USD` is unset.

To disable all three application spending caps, set `WEB_BUDGETS_ENABLED=0` in
the web process's environment and restart it. The production Cloudflare website
already selects this mode in `wrangler.toml`. The app then relies on the
project's API funding controls; old spending does not prevent a new authorized
attempt. The unchanged core receives an accounting estimate derived from each
frozen run's maximum token counts and bounded retries. Token, upload, timeout
and retry limits still apply. Set `WEB_BUDGETS_ENABLED=1` to restore the saved
caps, including historical charges.

Each paid submission requires the authorization checkbox. With caps enabled,
SQLite reserves the available amount in one transaction across the run, owner,
and deployment. Other
queued jobs count immediately. The worker reconciles accepted core reservations
and releases only unused allocations. Failed/uncertain calls retain charges;
hard-interrupted jobs retain the full allocation and require explicit retry.
No browser request changes the caps or receives the API key.

These are conservative local cost estimates, not provider-enforced billing
limits. When enabled, use the deployment cap alongside the provider's account
controls.
Existing run manifests retain their saved model, settings, and prices.

## Verification and current limits

```sh
.venv/bin/python -m pytest tests/local/test_web_extension.py tests/local/test_web_deployment.py -q
.venv/bin/python -m ruff check extensions/web tests/local/test_web_extension.py tests/local/test_web_deployment.py
```

Adapter tests use the real filesystem and core workflow with fictional offline
SDK responses. They skip when Flask is absent, so the extension does not become
a dependency of ordinary core use. The repository's offline network gate still
applies. No live test or paid call is needed.

This is an invited-test application on one persistent host, with text inputs,
independent project ownership, saved drafts, and one durable worker. It does not
provide collaborative editing, multi-host storage, or a web correction/relation
editor. The original CLI retains the full correction workflow. Container startup,
live Access sign-in, and the public route need verification on the chosen host.
