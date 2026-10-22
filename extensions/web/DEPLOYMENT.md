# Deploy the invited-tester website with Docker and Cloudflare

To host entirely within Cloudflare Workers, use the separate
[Workers deployment guide](../cloudflare/README.md). This guide describes the
alternative Docker server plus Cloudflare Tunnel setup.

This guide assumes independent testers, a domain you control in Cloudflare, and
one always-on machine with Docker Engine and Docker Compose v2. That machine
runs the Python application and stores the projects. Testers need only a browser
and access to their invited email address; they do not run Python or supply API
keys. Your laptop can host a short pilot, but the application goes offline when
it sleeps or disconnects.

## One repository; publish a service, not the repository root

Keep this single GitHub repository. The separation is:

| Location | Responsibility |
| --- | --- |
| `agentic_dt/`, `agents/`, `exercises/`, `config/` | Existing research workflow and canonical contracts |
| `extensions/web/` | Website, verified identity, project ownership, drafts, queue, deployment |
| `.github/workflows/web-checks.yml` | Offline checks and a container publication-boundary check |
| Docker image | Built runtime containing the required backend and intended web assets |
| Docker volume `agentic-reframe-data` | Private SQLite metadata, uploads, drafts, frozen runs, and per-project ledgers |

`dist/` is useful for a static Cloudflare Pages website. It cannot run this
filesystem-based Python workflow, hold private projects, or execute the worker.
For this application the Docker image is the release artifact. Only Flask's
explicit routes and `extensions/web/static/` are served over HTTP. Backend
source, project data, documentation, and the repository root are not static
website directories. The Docker build allowlist also excludes local projects,
credentials, and the repository's actual challenge brief.

The hosting path is:

```text
Tester's browser → Cloudflare Access → Cloudflare Tunnel → Python web service
                                                           │
                                                      SQLite + files
                                                           │
                                                    background worker → AI API
```

The application verifies Access's JWT signature, issuer, audience, expiry, and
human identity. An email typed into the research form or supplied in an arbitrary
HTTP header never establishes ownership or administrator rights. See
[Cloudflare JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

## 1. Prepare the source and server

Review and commit the intended changes, then push them through your normal
GitHub workflow. Nothing in the local setup automatically commits or pushes.
Wait for **Web extension checks → Offline tests and container build** to pass.
The workflow has read-only repository permissions and no deployment secrets;
it validates but does not publish anything.

Clone this same repository on the server and enter its root directory. Install
[Docker Engine](https://docs.docker.com/engine/install/) and the
[Compose plugin](https://docs.docker.com/compose/install/) using the instructions
for that server. All commands below run from the repository root, on the server.
No npm build or second frontend repository is required.

## 2. Choose the application hostname and Access team

Use a dedicated hostname such as `research.example.com`; replace that example
throughout this guide. Keep an existing studio website on its existing hostname
and Pages project.

In Cloudflare, open **Zero Trust** and create/select your organisation. Record
its team domain, for example `https://your-team.cloudflareaccess.com`. This is
the Access team domain, not `https://research.example.com`.

## 3. Enable individual email sign-in

In **Zero Trust → Integrations → Identity providers**, add **One-time PIN**.
This lets an invited tester authenticate through a short-lived code sent to
their email. Existing Google/Microsoft identity providers can also be used.
Follow [Cloudflare's OTP setup](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).

## 4. Protect the hostname with Access

In **Access controls → Applications**, choose **Add an application → Self-hosted**
and add the public hostname `research.example.com`, covering the whole hostname
and all paths. Choose a suitable sign-in session duration, such as one day.

Add an **Allow** policy with **Include → Emails** containing your own email and
each invited tester's email. Select One-time PIN as an allowed login method.
Use the explicit email list; an unrestricted Everyone or login-method-only
policy would not restrict admission to your cohort. Save the application and
policy before connecting the tunnel route.

Open the application's settings and copy its **Application Audience (AUD) Tag**.
The application uses that value to reject tokens issued for a different app.
See [Cloudflare's self-hosted application setup](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).

## 5. Create a remotely managed tunnel

Open **Networking → Tunnels** in the Cloudflare dashboard, create a
**Cloudflared** tunnel, and give it a descriptive name. The dashboard provides
a connector installation command containing a tunnel token. Copy the token
privately; do not commit it or paste it into the website.

In the tunnel's routes, add a **Published application**:

| Setting | Value |
| --- | --- |
| Public hostname | `research.example.com` |
| Service type | HTTP |
| Service URL | `web:8787` |

`web` is the service name on the private Compose network. Do not use
`localhost:8787` here: inside the connector container, localhost is the connector
itself. Cloudflare normally creates the hostname's DNS route when you add this
published application. Resolve any pre-existing conflicting DNS record rather
than adding a second target. See [Cloudflare Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/).

## 6. Create private deployment settings

```sh
cp extensions/web/deployment.env.example extensions/web/deployment.env
chmod 600 extensions/web/deployment.env
```

Edit `extensions/web/deployment.env` on the server:

| Variable | What to enter |
| --- | --- |
| `WEB_SECRET_KEY` | A new random signing secret, retained across restarts |
| `WEB_ACCESS_TEAM_DOMAIN` | The exact `https://your-team.cloudflareaccess.com` team domain |
| `WEB_ACCESS_AUD` | The self-hosted application's AUD tag |
| `WEB_ADMIN_EMAILS` | Your verified email; comma-separated if more than one administrator |
| `CLOUDFLARE_TUNNEL_TOKEN` | The connector token from the previous step |
| `WEB_LIVE_ENABLED` | Leave `0` for initial testing |
| `OPENAI_API_KEY` | Leave empty for initial testing; used only by the worker |
| `WEB_RUN_BUDGET_USD` | Maximum cumulative local estimate for one run |
| `WEB_USER_BUDGET_USD` | Allowance shared by one tester's projects and restarts |
| `WEB_TOTAL_BUDGET_USD` | Allowance shared by the whole deployment |

Generate the signing secret with `python3 -c 'import secrets; print(secrets.token_hex(32))'`
in your private server terminal, then put that value into the environment file.
Keep a protected backup of this file. It is ignored by Git and excluded from the
container build. Never show an expanded `docker compose config` containing these
values; use `config --quiet` for validation.

Administrator status comes from a verified Access email matching
`WEB_ADMIN_EMAILS`, not from the researcher name in a project form. Only give that
role to people who should be allowed to inspect the cohort's project summaries,
briefs, and reviewed exports. Adding a tester in Cloudflare grants admission;
the app still checks ownership on every project request.

## 7. Build and start the three services

```sh
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml config --quiet
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml up --build -d
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml ps
```

The services are `web`, `worker`, and `cloudflared`. The web service should become
healthy, and the tunnel should become Healthy in Cloudflare. No host port is
published: the connector reaches the web service on the private Docker network.
The API key is passed only to the worker. SQLite and core artifacts share the
persistent named volume; rebuilding the image does not replace the projects.

For startup problems, inspect these logs locally:

```sh
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml logs --tail=80 web worker
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml logs --tail=80 cloudflared
```

Do not paste tunnel tokens, Access assertions, session cookies, or API keys into
support messages. Treat the connector's startup output as private.

## 8. Verify identity and persistence before inviting everyone

1. Open `https://research.example.com`. Access should require sign-in.
2. Sign in using your allowed email. Your identity should appear in the header,
   along with **Administration** if your email is configured as an administrator.
3. Create a fictional project and save an incomplete exercise with **Save draft**.
4. Sign in with the same email on another machine/browser. Open **My projects**,
   select that project, and confirm the draft is present.
5. Sign in with a second invited email. It must not see or open the first
   tester's private project, even using its project/run URLs or IDs.
6. As administrator, open a project from **Administration** and explicitly publish
   its brief. A second tester can start an independent copy from **Available briefs**.
   Their copy should have no other tester's evidence, answers, runs, or reviews.
7. Restart the web and worker services and confirm the projects and drafts remain.
8. Confirm `/README.md`, `/agentic_dt/model.py`, `/web.sqlite3`, and
   `/extensions/web/deployment.env` return no file contents after sign-in.

Keep Cloudflare caching disabled for the authenticated application; the app sends
`Cache-Control: no-store`. Exercise changes, page links, project switching, and
uploads save changed drafts before navigation when JavaScript is enabled.
**Save draft** remains available; use it before refreshing or closing the page,
and when JavaScript is disabled. Conflicting saves from two devices return a
conflict with the submitted text retained for recovery.

## 9. Enable model calls deliberately

After the above checks, set `WEB_LIVE_ENABLED=1` and supply the server's
`OPENAI_API_KEY` in the private environment file. Review the three estimated
budget caps, then apply the environment change:

```sh
docker compose --env-file extensions/web/deployment.env -f extensions/web/compose.yaml up -d
```

Each run still requires the tester's spending authorization. A submission creates
a durable queued job; the page can be closed and revisited. One worker executes
jobs in order while other testers can read projects and save drafts. Research
history mutations wait until that project's active job finishes.

Quota reservations are atomic across testers. Accepted core reservations,
including failed calls with uncertain usage, remain charged in local estimates.
A worker interrupted during a call keeps its full outstanding allocation charged
and requires an explicit retry; it never automatically repeats that call.
If that exhausts an allowance, the host must inspect the run and review the caps
before authorizing more spending. Completed checkpoints remain available without
repeating their model calls.
These estimates do not enforce the provider's actual bill. Existing manifests,
model choices, and historical ledger events remain unchanged.

## 10. Updates, backups, and recovery

Use a tested Git commit on the server, then repeat the `up --build -d` command.
Allow a working analysis to finish before changing the worker image; its ten-minute
grace period permits a normal shutdown. A hard stop is handled as an interruption.
The single-worker constraint is enforced by a file lock on the shared data volume.
Do not scale the worker service or put this SQLite volume on a network filesystem.

Back up the entire `agentic-reframe-data` volume and the private environment file.
For a coherent simple backup, stop `web` and `worker` and use the host's volume
snapshot/backup facility before restarting them. Copying just SQLite while omitting
uploads, manifests, and ledgers does not preserve a project. Check restoration on
an isolated volume before relying on a backup. Never remove the named volume or
use `down --volumes` when retaining tester projects.

For application rollback, use the previous tested source commit/image and retain
the data volume. Do not restore older data over newer human reviews. Cloudflare
policies, the tunnel, DNS, and environment secrets are external settings; a code
rollback does not undo them.

Existing local prototype projects remain in their original directory. The new
extension registers legacy cookie-owned projects without scanning evidence or
rewriting their histories. If an existing local owner later signs in through
Access on that same installation, an explicit **Link my local projects** action
can transfer ownership. Moving old frozen runs to a different absolute filesystem
layout/container is a separate migration: export them first rather than editing
their historical manifests or silently changing their saved paths.

## Design reference and verification scope

The website uses Arizona Sans, a light blue wordmark, a decorative dot, open
spacing, text navigation, and fine rules. Dense research
forms use a white canvas and dark text rather than reproducing the portfolio's
full blue composition. There are no cards, shadows, animations, or frontend build.

Offline tests cover signatures and claims, owner isolation, cross-device
continuation, draft conflicts, template copies, duplicate enqueueing, atomic quota
reservations, interrupted jobs, and page responsiveness during a model call.
The CI workflow also builds the runtime image and checks excluded private files.
Live Cloudflare sign-in, the chosen server, and an actual provider call must be
verified on your deployment; local checks do not claim those external settings
have already been configured.
