# Workers pilot: development handoff

Updated 2026-10-21.

## Conclusion

The Cloudflare Workers adaptation reached a working, locally verified pilot.
It uses Python Workers, a singleton Durable Object, and private R2 storage. It
does not require Cloudflare Containers, a separate server, or an always-on laptop.
Your first hosted build uploaded successfully, but authenticated production use
is not yet verified.

The existing core package and canonical exercise/prompt/configuration files are
unchanged. The adapter is under `extensions/cloudflare/`; small dependency-injection
and import changes allow reuse of `extensions/web/`. The local/Docker host still
passes its tests. Changes have not been committed or pushed automatically.

## Completed verification

- Ruff lint and formatting checks passed for the changed Python sources/tests.
- Ordinary offline pytest: **123 passed, 1 skipped**. The skipped live service
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
- The supplied Cloudflare log records a successful build/deploy in 9m 7s. Most
  delay preceded the custom build: environment initialization and a requested
  Python installation. The guide now uses default build-image runtimes and
  `SKIP_DEPENDENCY_INSTALL=1` to skip the redundant root package installation.
- First-access regression reproduced in native Wrangler: the bare Access team
  hostname raises a configuration error inside `blockConcurrencyWhile`, resetting
  the object and escaping as an uncaught Worker exception. The issuer now includes
  `https://`, and request error handling runs inside the gate. Offline regressions
  cover invalid configuration and a failed R2 commit without advancing saved state.
- With the fix, repeated native requests using that same malformed issuer return
  readable HTTP 503 setup messages; requests without an Access assertion return
  HTTP 401. The runtime no longer throws the reproduced configuration exception.

The original port-8787 app and its data were not restarted or modified by these
checks. Native regression checks use a separate temporary cohort and no paid calls.

## Remaining verification

- Production Wrangler dry-runs did not run: automatic approval review hit a usage
  limit before launching the command. This was a review-service failure, not a
  judgment that the action was unsafe.
- Your hosted log confirms the website Worker was uploaded, and its `workers.dev`
  hostname presents Cloudflare Access sign-in. The corrected first-access bundle
  still needs deployment and verification after sign-in. The optimized build
  variables must be applied in each Worker's Build settings and timed on a new run;
  they are not runtime `[vars]` in Wrangler configuration.
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
