# Update the existing Cloudflare runner

The website continues to use the existing `Cohort` object and R2 bucket. The
private `agentic-reframe-runner` Worker now forwards to a separate SQLite-backed
`AnalysisRunner` Durable Object. SDK imports and model execution happen in that
object, under its default CPU allowance. No new repository or server is needed.

This targets Workers Free: SQLite-backed Durable Objects are available on Free
and use a default 30-second CPU allowance. Actual CPU, memory, R2 usage and
Durable Object duration must still fit the plan's quotas. Waiting for OpenAI
uses duration allowance even though it does not consume active CPU time.
See [limits](https://developers.cloudflare.com/durable-objects/platform/limits/)
and [free allowances](https://developers.cloudflare.com/durable-objects/platform/pricing/).

## 1. Push the code from your computer

Commit and push the backend changes to the GitHub branch already connected to
Cloudflare. Include the runner source, both runner configurations, fixture/tests,
and documentation. Keep `dist/`, `.wrangler/`, local data and credentials out of
the commit. The existing build command creates `dist/` again on Cloudflare.

## 2. Open the existing runner Worker

In your Cloudflare account, open **Workers & Pages → agentic-reframe-runner**.
Use this existing Worker, rather than creating a replacement or renaming it.
Its name is already referenced by the website's private service binding.

Under **Settings → Build**, confirm:

- The GitHub repository and production branch are the same as before.
- The build root is the repository root.
- The existing locked-dependency build command from [README.md](README.md#8-keep-one-github-repository)
  remains in place.
- The deploy command is:

```sh
cd extensions/cloudflare && .venv-build/bin/uv run pywrangler deploy --config wrangler.runner.toml
```

Keep the build variable `SKIP_DEPENDENCY_INSTALL=1`. The runner's deploy command
must use `wrangler.runner.toml`, not the website or fictional fixture configuration.

## 3. Deploy the new runner revision

If the Git push started an automatic build, wait for that build to finish.
Otherwise open **Deployments** and trigger a new build of the latest commit.

The committed configuration contains:

```toml
[[durable_objects.bindings]]
name = "ANALYSIS"
class_name = "AnalysisRunner"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["AnalysisRunner"]
```

Wrangler creates the SQLite-backed namespace and binding during deployment.
There is no manual database creation or schema command to run in the dashboard.
This is the runner Worker's first Durable Object migration. The website's
existing `Cohort` migration is separate and stays as it is.

The new configuration has no `[limits] cpu_ms` override. If you previously
manually set a CPU override in the runner's **Settings**, reset it to the plan's
default rather than adding a paid-plan override. The regular Worker is now only
a forwarder; the analysis object's default CPU allowance applies to execution.

## 4. Confirm the bindings and runtime settings

After deployment, inspect the runner's **Bindings**:

| Binding | Expected target |
| --- | --- |
| `ANALYSIS` | Durable Object class `AnalysisRunner`, SQLite-backed |
| `RESEARCH` | Existing private R2 bucket `agentic-reframe-private` |

In **Settings → Variables and Secrets**, confirm:

- `WEB_LIVE_ENABLED` is `1`.
- `OPENAI_API_KEY` is present as a runtime **Secret**. Retain the existing key;
  it does not need changing or copying into Build variables.

Keep the runner without a public domain, `workers.dev` route, or preview URL.
The website's `RUNNER` service binding still targets `agentic-reframe-runner`.
The SDK is loaded only inside the analysis object's authorized execution path.

## 5. Keep the website and saved projects

This runner change does not require a website redeployment or a new project.
If both GitHub-connected Workers rebuild from the push, their existing build
commands remain valid. Keep the website's Access settings, `WEB_SECRET_KEY`,
`Cohort` namespace, R2 bucket and service binding.

Do not delete or recreate the old coordinator/bucket to apply this change.
Existing uploads, frozen runs, reviews and spending history remain available.
Application dollar caps remain disabled by `WEB_BUDGETS_ENABLED=0` on the website.

## 6. Retry one saved analysis and inspect its execution

Open the website, reopen the interrupted run, refresh its page, check the paid
retry authorization, and press **Run AI analysis** once. This browser action
makes a newly authorized job; deploying the code alone makes no model calls.

In **agentic-reframe-runner → Observability → Invocations**, inspect the new
`AnalysisRunner` invocation. The normal forwarding invocation is still stateless;
the execution invocation should show `entrypoint: AnalysisRunner` and
`executionModel: durableObject`. Its logs should include:

1. `AnalysisRunner job …: executing in Durable Object`
2. `Runner job …: restoring snapshot`
3. `Runner job …: loading analysis runtime`
4. `Runner job …: initializing API client`
5. `Runner job …: executing analysis`
6. `Runner job …: result saved`

The website should advance to the saved result and human review. Inspect the
object's CPU and wall time to establish whether the real workload fits Free.
If it stops again, retain that new invocation's exception and timing before
authorizing another paid retry.

Repeated delivery of the same job ID returns its cached confirmed response.
A dispatched job without a confirmed response returns HTTP 409 and is not
automatically run again, even after the analysis object restarts. The browser's
explicit retry creates a different job ID. No job markers, old estimates, or
research history need clearing.
