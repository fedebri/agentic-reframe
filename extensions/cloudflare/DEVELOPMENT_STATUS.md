# Cloudflare pilot status

Updated 2026-10-22 after a repository audit. This describes committed code and
recorded verification; it does not independently verify the live account.

## Implemented

- The website Worker serves the Flask interface and verifies Access identities.
- The `Cohort` Durable Object coordinates projects, jobs, spending estimates, and
  immutable R2 snapshots. A separate `AnalysisRunner` Durable Object executes the
  analyst/critic workflow through the private runner Worker.
- Confirmed runner replies are cached; uncertain dispatches require an explicit
  new retry. Research ledgers and frozen artifacts retain their core contracts.
- Production TOML enables live calls on both Workers and disables application
  dollar caps on the website (`WEB_BUDGETS_ENABLED="0"`). Saved caps apply only
  when re-enabled. Local development disables live calls by default.
- Both production Workers enable observability. The website exposes its
  `workers.dev` hostname; the runner has no public route or preview URL.
- The pilot runs one analysis at a time with a 12 MiB uncompressed working-data
  limit across the cohort. Older R2 revisions consume additional storage.

See the [deployment guide](README.md) for setup and configuration. The
[runner upgrade guide](FREE_PLAN_UPDATE.md) applies to existing deployments that
need the separate analysis object. The local website preview remains available
in `extensions/web/`.

## Verification evidence

- Repository audit on 2026-10-22: **156 offline tests passed, 1 live test skipped**;
  Ruff lint passed across the core, extensions, and tests. No paid call was made.
- Previously documented native checks on 2026-10-21 covered uploads, project
  isolation, draft restart persistence, signed Access tokens, and the real SDK
  with a fictional provider, including bounded retries and human review. These
  emulator checks were not rerun for this audit.
- Recorded hosted failures reached `AnalysisRunner` and the API transport. The
  current code includes the separate analysis object, readable first-access
  configuration errors, and Fetch's `manual` redirect mode. Failed-job artifacts
  establish execution progress, not a completed provider analysis.

## Outstanding production checks

1. Verify the deployed revisions, invited/denied identities, cross-device project
   recovery, and persistence across deployment on the actual protected hostname.
2. With explicit spending authority, complete a fictional-input provider run,
   review it, and verify checkpoint reuse and interrupted-call accounting.
3. Recheck completed analysis/review persistence after a runtime restart and add
   repeatable native smoke checks to CI; current CI runs offline tests and builds.
4. Complete a full backup/restore drill covering R2 revisions and the coordinator's
   durable `head` pointer. A report ZIP is not a full storage backup.
5. Measure latency, memory, CPU, and storage with representative pilot data before
   expanding the cohort or changing the snapshot architecture.

Preserve historical snapshots, frozen manifests, and applied review history.
