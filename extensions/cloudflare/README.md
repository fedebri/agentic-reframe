# Cloudflare Workers deployment

This is a separate host adapter for the existing research website and Python
engine. It runs entirely on Cloudflare: no Docker server, Tunnel connector, or
always-on personal computer. The local/Docker host in `extensions/web/` still works.

The pilot is implemented and tested locally. The first hosted build has uploaded
successfully; authenticated production use still needs verification. See
[verification and next development work](DEVELOPMENT_STATUS.md) for the completed
checks and deployment gates.

## What runs where

| Component | Responsibility |
| --- | --- |
| Public Python Worker | Serve the existing Flask website and verify Access identities |
| One Durable Object (`Cohort`) | Serialize short changes, commit snapshots, record spending estimates, wake queued jobs |
| Private Python runner Worker | Forward service requests to the analysis object |
| Separate Durable Object (`AnalysisRunner`) | Import the SDK and execute the unchanged analyst/critic workflow |
| Private R2 bucket | Preserve immutable snapshots and analysis artifacts |
| Cloudflare Access | Invite testers using their email identities |

The adapter deliberately reuses SQLite and the core's existing files inside a
temporary working directory. After each short operation, it uploads a consistent
ZIP revision to R2 **before** advancing the Durable Object's durable `head` pointer.
That pointer, rather than the temporary filesystem, determines saved state.
Previous R2 revisions are retained. A failed upload leaves the previous head intact.

The job alarm commits its claim before contacting the private runner. During the
call, other testers can browse and save drafts. The runner returns only artifacts
from the claimed run; it cannot merge a ledger or replace newer drafts. The normal
human review remains the only route to applying claims.

The runner Worker forwards to one SQLite-backed `AnalysisRunner` object. The
object uses the default Durable Object CPU allowance; no paid-plan CPU override
is configured. Its durable job markers prevent repeating an uncertain dispatch,
and confirmed replies are cached for duplicate requests. A local asynchronous
lock serializes scratch-file use without holding `blockConcurrencyWhile` across
model calls. Only the coordinator's explicit retry creates a new job ID.

For an existing deployment, follow the focused
[Durable Object runner update steps](FREE_PLAN_UPDATE.md).

Exercise navigation, skips and revision intent use the existing private project
index and are checkpointed with the cohort snapshot. Deploy navigation changes
to `agentic-reframe` with the existing website build/deploy commands; the runner
protocol, bindings and migration tags are unchanged. Existing projects derive
progress from their saved runs and review receipts, without a reset or database
migration. See [the website navigation guide](../web/README.md#exercise-navigation).

This is a **small-cohort pilot**, with one analysis running at a time and a **12 MiB
uncompressed working-data limit across the cohort**. Each operation restores and
packs the cohort snapshot. This preserves the existing engine with a small adapter,
but is not a design for large uploads or an unlimited number of projects. Historical
R2 revisions are outside this working-data limit and still consume storage. Before
a larger rollout, measure latency/memory with representative data and move metadata
and individual artifacts to a more granular storage design.

## 1. Install local development tools

These commands run in **Terminal on your Mac**, only while developing/deploying.
Cloudflare keeps the deployed application running after your Mac is turned off.

Install [Node.js 22 or later](https://nodejs.org/en/download) and
[uv](https://docs.astral.sh/uv/getting-started/installation/) if needed. Then:

```sh
cd /Users/f1/Documents/github_repos/agentic_dt/extensions/cloudflare
npm ci
uv sync --locked
uv run python build.py
uv run pywrangler sync
```

`uv.lock` pins the local tooling, `pylock.toml` pins WebAssembly-compatible packages,
and `package-lock.json` pins the tested Wrangler version. Do not silently regenerate
them during deployment. `pywrangler sync` installs those packages for Workers.

## 2. Try the website locally

```sh
uv run pywrangler dev --env local --port 8790
```

Open <http://127.0.0.1:8790>. This uses a separate local R2/Durable Object emulator,
fictional browser identities, and disabled AI calls. Your existing port-8787 app
and its project files are separate.

From another terminal in this folder:

```sh
uv run python smoke.py
```

Stop/restart this Wrangler process with the same command, then:

```sh
uv run python smoke.py --resume
```

That checks real uploads, project isolation, independent drafts, frozen runs and
runtime restart persistence. Local state stays under the ignored `.wrangler/` folder.
The local identity mode rejects non-loopback URLs; never deploy `--env local`.

## 3. Test analysis without paying for API calls

The optional provider fixture is in `tests/workers/fixture.py`. It intercepts all
outbound provider requests, returns clearly fictional claims, and injects one HTTP
429 to exercise the existing bounded retry logic. It is excluded from the production
bundle. No real API key is needed or used.

Build both bundles, then start the fixture in one terminal:

```sh
uv run python build.py
uv run python build.py --fixture
uv run pywrangler dev --config wrangler.fixture.toml --port 8791
```

Start the website in another terminal, replacing its ordinary preview process:

```sh
uv run pywrangler dev --env local --port 8790 \
  --var WEB_LIVE_ENABLED:1 \
  --var WEB_RUN_BUDGET_USD:0.10 \
  --var WEB_USER_BUDGET_USD:0.50 \
  --var WEB_TOTAL_BUDGET_USD:5.00
```

Then, from a third terminal:

```sh
uv run python smoke.py --analysis
```

The script submits a fictional review **only to its loopback test project**. It
checks the native alarm, service binding, analysis Durable Object, real SDK with
the provider stub, critic, concurrent draft save and applied review. Restart the
website and run `--resume` again to verify that the completed results also persist.
Never deploy the fixture configuration or point this script at a real cohort.

## 4. Prepare Cloudflare

In the Cloudflare dashboard:

1. Choose the account that owns your website's domain. The runner uses a
   SQLite-backed Durable Object, which is available on Workers Free. CPU/memory
   and R2/DO quotas still need monitoring; deployed Free-plan capacity must be
   checked with representative inputs. See
   [Durable Object limits](https://developers.cloudflare.com/durable-objects/platform/limits/).
2. Enable R2 and create a bucket named `agentic-reframe-private`. Leave public access
   and `r2.dev` disabled. Both production configurations bind this bucket.
3. Choose a separate hostname, for example `research.your-domain.com`.
4. Open Zero Trust, configure your team domain and enable **One-time PIN** as an
   identity provider if you want email login.
5. Add a **self-hosted Access application** covering the entire research hostname,
   all paths. Add an Allow policy with the explicit invited email addresses,
   including your administrator email. Avoid a broad Everyone policy.
6. Copy the Access application's **AUD** value and your team issuer URL, such as
   `https://your-team.cloudflareaccess.com`.

See the official guides for
[email PIN login](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/),
[self-hosted Access applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/),
and [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/).

## 5. Set the production configuration

Edit `wrangler.toml` in this folder:

```toml
[vars]
WEB_ACCESS_TEAM_DOMAIN = "https://your-team.cloudflareaccess.com"
WEB_ACCESS_AUD = "your-application-audience"
WEB_ADMIN_EMAILS = "your-email@example.com"
WEB_LIVE_ENABLED = "0"
WEB_BUDGETS_ENABLED = "1"
WEB_RUN_BUDGET_USD = "0.50"
WEB_USER_BUDGET_USD = "2.00"
WEB_TOTAL_BUDGET_USD = "5.00"
```

Keep the other configuration sections. The issuer, AUD and admin email are settings,
not API credentials. The app verifies signed Access tokens; an arbitrary email
header is insufficient. Keep live calls disabled for the first deployment.

The website currently enables `workers.dev`; protect that entire hostname with
Cloudflare Access, including every path. The private runner disables `workers.dev`
and has no public routes. Both disable preview URLs. Only the website Worker should
receive a research custom domain. Set its `workers_dev = false` if you later serve
it exclusively through that protected custom domain.

In Terminal, sign into Cloudflare:

```sh
uv run pywrangler login
```

Generate a stable signing secret with a password manager or:

```sh
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

Keep it in your password manager. It signs browser sessions; changing it signs
testers out. Never put it in Git or a committed configuration file.

## 6. Build, check, and deploy

From this same folder:

```sh
uv run python build.py
uv run pywrangler deploy --config wrangler.runner.toml --dry-run
uv run pywrangler deploy --env "" --dry-run
uv run pywrangler deploy --config wrangler.runner.toml
uv run pywrangler deploy --env ""
uv run pywrangler secret put WEB_SECRET_KEY --env ""
```

Paste the signing secret when prompted by the last command. The runner is deployed
first so the website's service binding can resolve it. The website is reachable on
its Access-protected `workers.dev` hostname. Missing Access settings or the session
secret return a setup error without allowing access. `--env ""` explicitly selects
the production configuration; never deploy `--env local`.

After creating the Access application and setting the signing secret, append your
custom domain to **`wrangler.toml` only**:

```toml
[[routes]]
pattern = "research.your-domain.com"
custom_domain = true
```

Deploy the website again with `uv run pywrangler deploy --env ""`. Keeping the domain in
configuration preserves it on later deployments. Keep the runner without a domain
or route. Cloudflare manages the DNS/TLS connection; no Tunnel or external server
is needed. Confirm the domain in **Workers & Pages → agentic-reframe → Settings →
Domains & Routes**.

Visit the hostname, sign in, create a project and save a draft. In a separate
browser/machine, use another invited identity and confirm it has its own project
list. Sign in again as the first identity and reopen its saved project. Try a
non-invited address and confirm Access refuses it. The administrator can inspect
the cohort at `/admin` and publish a brief for independent copies as before.

## 7. Enable real analysis deliberately

The current production configurations enable live analysis on both Workers.
The website sets **`WEB_BUDGETS_ENABLED = "0"`**, so the application does not
enforce run, tester, or deployment dollar caps. Paid calls use the project's
API funding controls. The saved $0.50/$2.00/$5.00 values are ignored in this mode.
Local development keeps live calls disabled. For a new staging installation,
keep the production live flags at `"0"` until the non-AI deployment checks pass.

Before enabling the website for testers, add the key as a runtime **Secret** on
**agentic-reframe-runner**, using **Settings → Variables and Secrets → Add**:
name `OPENAI_API_KEY`, type **Secret**, then save and deploy. Do not add it to the
website Worker, Build variables, or Git. Alternatively, from Terminal:

```sh
uv run pywrangler secret put OPENAI_API_KEY --config wrangler.runner.toml
```

Paste the API key into that prompt. It belongs **only to the private runner**.
Both production TOML configurations now set `WEB_LIVE_ENABLED = "1"`. Commit/push
the configuration changes and deploy **the runner first, then the website**. This
activation requires updating both Workers, even if an earlier website-only fix did
not. Confirm the browser shows that real AI requests are enabled.

Open a project, save the independent interpretation, preview a request, check the
authorization checkbox, and choose **Run AI analysis**. This is the action that
launches the paid call; enabling the feature alone does not queue an analysis.

The model, reasoning and price estimates come from the existing project config and
are frozen into each run. An explicit browser authorization queues each analysis.
The unchanged core still receives a finite accounting estimate covering the run's
maximum input/output tokens and bounded retries, including the optional critic.
This estimate covers all permitted calls without adding a dollar spending cap.
Token, upload, timeout and retry limits remain in effect.

Spending history remains recorded, including earlier interrupted allocations;
it does not block new authorized attempts while application caps are disabled.
To reinstate the saved caps, set `WEB_BUDGETS_ENABLED = "1"` in `wrangler.toml`
and redeploy the website. Historical charges will count again, across each
tester's projects and the whole deployment. This setting belongs to the website
Worker; the runner needs only its existing live flag and API key.

An alarm/runner interruption retains the full allocation, marks the job interrupted,
and requires explicit human retry consent. A timed-out request might still have
been billed; it is never automatically launched again by an alarm retry. Existing
completed checkpoints are reused. Runner configuration errors before execution do
not incur a model reservation.

## 8. Keep one GitHub repository

The same repository contains core code, the existing local host, and this adapter.
`build.py` stages only approved source/resources into this folder's ignored `dist/`.
It replaces the repository's real brief with a neutral scaffold and excludes private
uploads, existing runs, environment files and the fixture. Unexpected stale files in
`dist/` block the build. Do not upload the repository as public static assets.

Here, `dist/` is the **Worker bundle staging directory**, not a static HTML site.
The backend is bundled for execution inside Workers; Flask exposes only its normal
routes and static assets. You do not need a second repository.

For GitHub-connected deployments, create two Workers Builds projects pointing to
this repository, one per production Worker. Keep the repository root as their root
directory so the build can read the core.

For **each Worker**, open **Settings → Build → Build variables and secrets**:

1. Add the plaintext build variable `SKIP_DEPENDENCY_INSTALL` with value `1`. The
   custom command below installs the extension's locked dependencies; Cloudflare's
   automatic root-level `pip install .` is redundant.
2. Remove a `PYTHON_VERSION` override, especially `3.12` or `3.12.15`. Use the build
   image's default Python, which meets this extension's `>=3.12` requirement. That
   avoids requesting the extra interpreter installation seen in the slow build.
3. Remove a `NODE_VERSION` override unless needed for another reason. The image's
   default Node meets the extension's `>=22` requirement.

These are **build environment** settings, not Worker runtime variables. Adding
them to `[vars]` in `wrangler.toml` cannot change the build environment. See
[Cloudflare's build image settings](https://developers.cloudflare.com/workers/ci-cd/builds/build-image/).
Do not add root-level Python/Node version files to force downloads for this adapter.
The deployed WebAssembly runtime and packages remain pinned separately by the
Workers configuration and `pylock.toml`.

For both Workers, use this build command; `--python` reuses the interpreter already
selected by the build image, and tool installation stays inside the project:

```sh
cd extensions/cloudflare
python -m venv .venv-build
.venv-build/bin/python -m pip install 'uv==0.13.4'
npm ci
.venv-build/bin/uv sync --locked --python .venv-build/bin/python
.venv-build/bin/uv run python build.py
```

Use this deploy command for the runner:

```sh
cd extensions/cloudflare && .venv-build/bin/uv run pywrangler deploy --config wrangler.runner.toml
```

For the website:

```sh
cd extensions/cloudflare && .venv-build/bin/uv run pywrangler deploy --env ""
```

Keep secrets on their respective Workers. Validate manual deployment first. When a
change updates the runner protocol, deploy the runner before updating the website;
independent automatic builds do not guarantee that order. Keep automatic deployment
disabled for branches used for fixture tests.
The supplied hosted log confirms that the earlier build/deploy command completed.
The optimized build variables still need applying and timing on your account.
Enabling build caching alone is not the primary fix: Cloudflare currently documents
automatic dependency caching for Node package managers, and this monorepo keeps
`package.json` under the extension rather than the build root. Do not assume it
caches `uv` or the WebAssembly packages. See
[build caching](https://developers.cloudflare.com/workers/ci-cd/builds/build-caching/).

## Troubleshoot first access

The Access issuer must include `https://`. A bare team hostname is invalid. The
Worker now returns a readable HTTP 503 for an invalid issuer or missing
`WEB_SECRET_KEY`, rather than letting that error reset its Durable Object and
surface as a generic Worker/JavaScript exception. Correct the setting and redeploy
the website; existing project snapshots do not need resetting.

If the generic exception persists, open **Workers & Pages → agentic-reframe →
Observability → Real-time logs**, start the live log stream and reload the website
after signing in. Record the exception and timestamp; a successful build proves
the bundle uploaded, not that authenticated application requests work. Keep tokens,
cookies and API keys out of shared logs. A 401 after sign-in points instead to the
Access token, issuer or application AUD; keep signature verification enabled.

The normal landing page is `/`. A message that Cloudflare signing keys are
temporarily unavailable means the website could not retrieve the public keys
needed to verify the Access token; it is not a separate login landing page.
Opening Home can succeed because it makes a new verification attempt.
The adapter retains PyJWT's five-minute public-key cache across requests and
retries network errors, HTTP 429 and server errors once, after 250 ms. Each fetch
still has a five-second timeout. Persistent failures return HTTP 503; every
request still checks the token's signature, issuer, audience and expiry. The
cache is replaced when the configured issuer or audience changes.

### An analysis stops and its allowance is exhausted

If the private runner returns a non-200 response, its connection fails, or the
coordinator recovers an interrupted job, the allocation is retained because
provider execution/billing is uncertain. When application caps are enabled,
retaining $0.50 exhausts a $0.50 run allowance even when the tester/deployment
still has funds. With `WEB_BUDGETS_ENABLED = "0"`, that retained estimate does
not prevent an explicitly authorized retry. The recorded estimate does not
establish the provider's actual charge. Keep the failed run and frozen inputs;
do not clear spending or automatically retry.

Both production Workers now enable Cloudflare Observability. Deploy the runner,
then the website, to apply diagnostics. Previously unrecorded logs cannot be
recovered by enabling logging later. In **Workers & Pages → select Worker →
Observability**, inspect the failed invocation and its outcome/exception. Check
both the runner's `/execute` request and the website's alarm invocation.

The runner logs its job ID at snapshot restore, API-client initialization,
analysis execution and result save. These markers contain no API key, source
text, or model request body. The website retains the runner's HTTP status or
exception type for new failed calls and displays **interrupted** rather than
the unchanged **prepared** artifact status. Existing saved error messages remain.
Disabling application caps does not diagnose or repair the runner interruption.
Use these logs if the next authorized attempt also stops.

### Runner CPU limit during SDK import

The supplied production traces for 2026-10-21 show
`introspection.CpuLimitExceeded: Python Worker exceeded CPU time limit`
while `/execute` imports `extensions.web.worker` and the OpenAI SDK. The two
invocations consumed 1,997 and 2,040 ms of CPU time before stopping. They failed
before the route reached any provider request; the website then reported the
cancelled service-binding request as `AbortError`. The accompanying ZIP
deallocator errors appear to be cleanup errors from the same interruption.

The runner now executes `/execute` in the separate SQLite-backed
`AnalysisRunner` Durable Object. The regular Worker only forwards requests and
does not import the SDK during that handler. `wrangler.runner.toml` registers
the object using an `ANALYSIS` binding and a `v1` `new_sqlite_classes` migration;
the earlier paid-plan `[limits] cpu_ms` override has been removed.

The default Durable Object CPU allowance is 30 seconds. CPU time is separate
from the model's network timeout; waiting for the provider does not consume CPU
allowance, but does count toward Durable Object duration usage. See
[Durable Object limits](https://developers.cloudflare.com/durable-objects/platform/limits/)
and [free allowances](https://developers.cloudflare.com/durable-objects/platform/pricing/).
Follow [the existing-deployment update steps](FREE_PLAN_UPDATE.md), then reopen
the saved interrupted run and explicitly authorize one retry. Preserve the
existing coordinator and bucket; their data does not require migration.

Ordinary offline tests cover forwarding, concurrent duplicates, cached replies,
interrupted-job recovery, and the new SQLite migration. The native provider
fixture uses the same forwarder and analysis object as production. These checks
do not verify Cloudflare's deployed CPU enforcement or make paid API calls.
The core engine, model settings, saved manifests, and spending history retain
their existing contracts.

### APIConnectionError after successful Durable Object dispatch

The 2026-10-22 trace reached `AnalysisRunner`, used 5,122 ms of CPU, and saved a
failed-job artifact with `APIConnectionError`. The Durable Object CPU adjustment
was active; HTTP 200 for `/execute` means the job outcome was saved, not that the
model returned an analysis.

The HTTP adapter previously passed `redirect="error"` to Fetch. A native Wrangler
probe reproduced `TypeError: Invalid redirect value` before contacting OpenAI.
Workers supports only `follow` and `manual`; the adapter now uses `manual` to
return redirects without following them. See
[Request redirect modes](https://developers.cloudflare.com/workers/runtime-apis/request/).
The local provider fixture now constructs a native Request before stubbing the
network, so it also validates those Fetch options.

Push this fix and redeploy `agentic-reframe-runner` with the existing build and
deploy commands, then explicitly authorize one retry from the saved run page.
No binding, secret, migration tag or CPU setting needs changing for this fix.
The trace's `INFO:runner:...` lines are informational messages written to stderr
and consequently labelled `error` by Cloudflare. The ignored ZIP deallocator
exception is separate from the connection failure; execution continued past it.

### Why the SDK is not imported into the deployment snapshot

Cloudflare [snapshots module-level imports during deployment](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/#deployment-lifecycle-and-cold-start-optimizations).
An import in the GitHub build process alone does not populate that snapshot.
However, the pinned `openai==2.54.0` imports its Bedrock integration, which calls
`os.urandom(32)` at module level. An isolated native Wrangler 4.151.3 probe
reproduced a startup failure: `Randomness is not allowed while a Worker is starting`.
The probe used no API key and made no provider calls.

Keep the SDK import inside execution for this version. Python caches a successful
import within the Worker instance, so the import cost is paid on its first use.
Moving it into the snapshot requires an SDK change that defers the import-time
random key initialization. API clients and credentials should still be created
during request execution. Do not replace secure randomness with fixed values to
make snapshot creation succeed.

## Operations and current boundaries

- Full disaster recovery needs both the private R2 revisions and the Durable
  Object's current `head` pointer. A complete export/restore procedure and drill
  remain development work before collecting important real research data. Preserve
  immutable revisions; do not add expiration/deletion to snapshot/result prefixes.
- The existing report export remains available; it is not a complete storage backup.
- Do not rename the `Cohort` class, `cohort-v1` object name, Worker/bucket bindings,
  or `/tmp/agentic-reframe` paths without a migration. Frozen artifacts refer to
  stable virtual paths. Never rewrite old manifests or ledgers to make a resume fit.
- This host starts a new cohort. Existing local/Docker projects stay where they are;
  moving their absolute-path manifests requires a separate explicit migration.
- Keep production access checks enabled on every application path. Only `/health`
  exposes a public status response. Do not share raw R2 snapshot URLs or credentials.
- Ordinary repository tests remain offline. `smoke.py` is an explicit local-runtime
  integration check; a real deployed paid call has not been made automatically.

Relevant platform documentation:
[Python Workers](https://developers.cloudflare.com/workers/languages/python/),
[Flask adapter](https://developers.cloudflare.com/workers/languages/python/packages/flask/),
[Durable Object alarms](https://developers.cloudflare.com/durable-objects/api/alarms/),
[R2 bindings](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/).
