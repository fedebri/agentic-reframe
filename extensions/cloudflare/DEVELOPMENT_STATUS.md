# Workers pilot: development handoff

Updated 2026-10-21.

## Conclusion

The Cloudflare Workers adaptation reached a working, locally verified pilot.
It uses Python Workers, a singleton Durable Object, and private R2 storage. It
does not require Cloudflare Containers, a separate server, or an always-on laptop.
It is not yet a verified public production deployment.

The existing core package and canonical exercise/prompt/configuration files are
unchanged. The adapter is under `extensions/cloudflare/`; small dependency-injection
and import changes allow reuse of `extensions/web/`. The local/Docker host still
passes its tests. Changes have not been committed or pushed automatically.

## Completed verification

- Ruff lint and formatting checks passed for the changed Python sources/tests.
- Ordinary offline pytest: **120 passed, 1 skipped**. The skipped live service
  test was not enabled.
- WebAssembly dependencies built successfully using the locked Python Workers
  toolchain. Native checks used Wrangler **4.151.3**.
- The actual Workers emulator served the existing Flask website.
- Fictional browser smoke checks passed: project creation, partial draft, multipart
  evidence upload, frozen run preparation, and separate-browser ownership isolation.
- A saved project and draft survived stopping/restarting the Workers runtime.
- Native analysis smoke checks passed using the **real SDK and core workflow** with
  only the external provider replaced: alarm, private service binding, analyst,
  optional critic, simulated HTTP 429/bounded retry, concurrent draft save, and
  explicit human review. No paid AI API calls were made.
- Native RSA Access verification accepted a valid fictional signature and rejected
  a token with the wrong audience.
- Offline failure checks cover R2 commit failure, data-size rejection, interrupted
  job accounting, append-only artifact merging, and production bundle boundaries.

The temporary native preview/fixture processes have been stopped. The original
port-8787 app and its data were not restarted or modified by these checks.

## Remaining verification

- Production Wrangler dry-runs did not run: automatic approval review hit a usage
  limit before launching the command. This was a review-service failure, not a
  judgment that the action was unsafe.
- No real Cloudflare R2 bucket, Access policy, Worker, custom domain or secrets
  were created/configured. The hosted GitHub/Workers Builds setup is documented,
  but has not run against your account.
- No paid model call has been verified from a deployed Worker.
- The final completed analysis/review has not yet been rechecked after a second
  runtime restart; earlier project/draft restart persistence was verified.
- Representative memory/latency tests and a full backup/restore drill remain open.

## Next development steps, in order

1. **Deploy a private staging cohort with AI disabled.** Follow `README.md`, run both
   production dry-runs, set Access/AUD/session secret, and attach the custom domain
   through `wrangler.toml`. Check two invited identities on two machines and reject
   an uninvited identity. Confirm project persistence across a deployment.
2. **Check one real, fictional-input analysis with an explicit small spending
   allowance.** Put the key only on the private runner, enable both live flags, and
   confirm results, review, budget accounting and failure/retry behaviour.
3. **Harden operations before important research data.** Implement full snapshot
   export/restore including the durable head pointer, run a recovery drill, and
   automate the native fixture smoke/restart tests in CI.
4. **Measure pilot limits before expanding.** This version has one active analysis
   at a time and a 12 MiB uncompressed working-data cap across the cohort. Benchmark
   representative projects. If those limits are restrictive, move metadata and
   individual artifacts to granular Cloudflare storage rather than raising the
   snapshot limit blindly.

Keep real deployment and budgeted service checks separate from ordinary offline
pytest. Preserve old snapshots, frozen manifests, and applied review history.
