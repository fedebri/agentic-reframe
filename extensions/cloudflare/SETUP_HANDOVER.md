# Cloudflare setup: conversation handover

Updated: 2026-10-21. This document summarizes the deployment discussion,
user-reported dashboard actions, and repository settings inspected at handover.
Dashboard state has not been independently verified. No credentials are included.

## Project and architecture

The project supports evidence-tracked design framing exercises: people record
an independent interpretation, assign evidence, request AI analysis, and review
claims before applying them. Cloudflare hosting lets invited testers use separate
machines at different times without keeping the developer's computer running.

The existing Python engine remains in `agentic_dt/`. The website adapter is in
`extensions/web/`; the Cloudflare extension is in `extensions/cloudflare/`.
One GitHub repository is sufficient. The build generates the deployment bundle
under `extensions/cloudflare/dist/`; the two Wrangler configurations choose the
entry points and bindings. A separate website repository is unnecessary.

| Component | Purpose | Public access |
| --- | --- | --- |
| `agentic-reframe` | Website and Access identity verification | Protected website URL |
| `agentic-reframe-runner` | Executes analyst/critic jobs | Private service binding only |
| `Cohort` Durable Object | Coordinates saved revisions, jobs and budgets | Through website |
| `agentic-reframe-private` R2 bucket | Immutable snapshots and run artifacts | Private |
| Cloudflare Access | Authenticates invited testers | Login gateway |

This is a small-cohort pilot: one analysis at a time and a 12 MiB uncompressed
working-data limit across the cohort. Historical R2 revisions also consume storage.
The Workers Paid plan was recommended for CPU headroom; production CPU needs have
not yet been measured. Hosting charges, storage and model API charges are distinct.

## Completed during the setup discussion

- The user updated GitHub and connected it to Cloudflare Workers Builds.
- The user created the private R2 bucket `agentic-reframe-private`.
- The user reported successful builds/deployments of both the runner and website.
- The user activated a Zero Trust organization and configured Access policies.
  Exact invited-email rules and complete hostname coverage still need confirmation.
- The default website address was chosen:
  <https://agentic-reframe.drvr-web.workers.dev>.
- The website configuration enables `workers_dev`; the runner keeps it disabled.
  Both configurations disable preview URLs.
- A GitHub Actions test initially failed because it required both Workers to
  disable `workers_dev`. The user reported updating and pushing the test so the
  website can be public while the runner remains private. A subsequent successful
  CI result was not supplied in this conversation.
- The Access application AUD was added to the website's `[vars]` configuration.
- The latest local configuration also contains the full HTTPS Access team URL.
  This supersedes the earlier finding that it still contained a placeholder.

## Cloudflare build settings discussed

Create two Workers connected to this same repository. Keep the build root at the
repository root and choose the branch actually used for deployment.

The shared build command supplied during setup was:

```sh
cd extensions/cloudflare && python -m venv .venv-build && .venv-build/bin/python -m pip install 'uv==0.13.4' && npm ci && .venv-build/bin/uv sync --locked && .venv-build/bin/uv run python build.py
```

Runner deploy command:

```sh
cd extensions/cloudflare && .venv-build/bin/uv run pywrangler deploy --config wrangler.runner.toml
```

Website deploy command:

```sh
cd extensions/cloudflare && .venv-build/bin/uv run pywrangler deploy --env ""
```

The `--env ""` selects production explicitly. Never deploy `--env local`.
The generic `npx wrangler deploy` default was replaced with the Python Workers
toolchain command. Nonproduction builds/previews were to remain disabled initially;
their default preview command is not part of the production workflow.

Earlier advice suggested Node 22 and Python 3.12 build variables. The current
[development status](DEVELOPMENT_STATUS.md) records a later optimization using
the build image's default runtimes and `SKIP_DEPENDENCY_INSTALL=1`; consult that
document for the latest build advice. Build variables belong in Build settings,
not the Worker's runtime Variables and Secrets.

Deploy the runner before the website when first creating both services. If a later
change affects only website configuration, only the website needs redeployment.
A test-only change does not itself require redeploying runtime code. Automatic
rebuilds were not confirmed working; check the Git integration, production branch
and build history before relying on push-triggered deployment.

## Access and runtime configuration

The website's `wrangler.toml` contains the nonsecret production settings under
`[vars]`. Keep these in source configuration so subsequent deployments retain them.

| Setting | Required value or current status |
| --- | --- |
| `WEB_ACCESS_TEAM_DOMAIN` | Full `https://TEAM.cloudflareaccess.com` issuer; now populated locally |
| `WEB_ACCESS_AUD` | Audience from the Access application protecting this website; populated locally |
| `WEB_ADMIN_EMAILS` | Intended administrator email(s); currently empty locally |
| `WEB_LIVE_ENABLED` | Currently `"0"`; AI calls disabled |
| `WEB_RUN_BUDGET_USD` | Currently `"0.10"` |
| `WEB_USER_BUDGET_USD` | Currently `"0.50"` |
| `WEB_TOTAL_BUDGET_USD` | Currently `"5.00"` |

Set `WEB_SECRET_KEY` as a runtime **Secret** on the website Worker, through
Workers & Pages → agentic-reframe → Settings → Variables and Secrets. Use a stable,
long random value and keep a private backup. Its existence in production has not
been confirmed. The fictional key in `[env.local.vars]` is only for local testing.

The runner does not need the Access AUD or the website session secret. A real
`OPENAI_API_KEY` belongs only on the runner, and paid analysis requires explicitly
enabling live calls on both Workers. Do this after the basic website works and a
test spending allowance has been agreed.

### Access policy choices

- Protect **all traffic** to the website, including all paths on its `workers.dev`
  address. A custom domain is optional; protecting a different hostname alone does
  not establish protection for this URL.
- Enable One-time PIN if testers should log in with emailed verification codes.
- The Worker's simplified Access panel offers email-domain or Cloudflare-account
  policies. Edit the created application in Zero Trust → Access → Applications
  for advanced rules such as an Allow policy containing exact invited emails.
- An email-domain rule admits any verified address at that domain. A Cloudflare
  account rule admits account members. External testers can use exact email rules
  without becoming Cloudflare account members.
- Use the AUD from the application that actually protects this website.

## Current blocker: first website visit

The user encountered **Error 1101: Worker threw exception** at
`2026-10-21 16:21:16 UTC`, Ray ID `a4e197fe9f1fb541`.
This establishes a runtime exception, not its cause. The exception traceback from
the hosted Worker has not been supplied in this conversation.

The initial investigation identified the issuer URL and missing session secret as
configuration checks. The issuer is now a full HTTPS URL in the local file.
The current development status separately records a reproduced first-access
configuration failure and an error-handling fix; those verification results are
reported there, not rerun for this handover. The corrected bundle still needs
production deployment and verification.

Next steps:

1. Confirm the latest corrected website code and HTTPS issuer are on the deployed
   branch, then rebuild/deploy `agentic-reframe`.
2. Confirm `WEB_SECRET_KEY` exists as a production runtime secret on that Worker.
3. Open its Observability / real-time logs, start streaming, and refresh the website.
   Both local production configurations currently set observability to disabled;
   enable logging if needed for diagnosis and account for configuration on redeploy.
4. If the error persists, capture the exception message and traceback, excluding
   secrets. The 1101 page alone is insufficient to choose a code fix.

## Acceptance checks after the website opens

1. An invited email can authenticate; an uninvited identity is denied.
2. A second tester/browser has separate owned projects and drafts.
3. A project, exercise selection, draft and uploaded evidence can be saved and
   recovered after a new session and deployment.
4. AI calls remain disabled until intentionally configured and authorized.
5. A later, budgeted fictional-input run verifies the real provider path, human
   review and budget accounting. No successful deployed paid call is confirmed here.
6. Before important research data, verify backup/restore and representative resource
   usage. Do not infer production reliability from a successful build alone.

Expected first visit: Access sign-in (unless already authenticated), then the
project website. An Access denial points to policy configuration; a setup message
points to application configuration; a 1101 requires the runtime exception log.

## References

- [Repository deployment guide](README.md)
- [Development verification and remaining work](DEVELOPMENT_STATUS.md)
- [Website Wrangler configuration](wrangler.toml)
- [Private runner configuration](wrangler.runner.toml)
- [Cloudflare Workers errors](https://developers.cloudflare.com/workers/observability/errors/)
- [Cloudflare Workers Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/)
- [Cloudflare Workers Builds configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/)
- [Cloudflare runtime secrets](https://developers.cloudflare.com/workers/configuration/secrets/)

This handover adds documentation only. It does not change code, deploy a Worker,
alter Cloudflare settings, or establish that the remaining checks have passed.
