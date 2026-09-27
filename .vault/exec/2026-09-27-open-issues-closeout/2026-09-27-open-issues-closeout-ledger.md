---
tags:
  - '#exec'
  - '#open-issues-closeout'
date: '2026-09-27'
modified: '2026-09-27'
body_schema: 'body-v2'
body_hash: 'sha256:552ab3d3c234cb52a1f1e0c1ef1a5a5dee3b3e2f47b1d1bfdd82b9fe569e0e4a'
related:
  - "[[2026-09-27-open-issues-closeout-plan]]"
---

# `open-issues-closeout` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/search/_typesafe_transport.py`
- `S01` `M` `src/vaultspec_rag/tests/test_typesafe_transport.py`
- `S01` `verify:` `focused unit and loopback regressions (101 tests)` -> `pass`
- `S01` `verify:` `model-state mutation fail-restore-pass` -> `pass`
- `S01` `verify:` `ruff lint and format` -> `pass`
- `S01` `verify:` `ty and configured basedpyright` -> `pass`
- `S02` `M` `.github/workflows/publish.yml`
- `S02` `M` `tools/binaries/tests/test_release_workflow.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_service_jobs_cli_basics.py`
- `S02` `verify:` `focused unit and loopback regressions (101 tests)` -> `pass`
- `S02` `verify:` `unique-package and docs flag/fence mutations fail-restore-pass` -> `pass`
- `S02` `verify:` `ruff lint and format` -> `pass`
- `S02` `verify:` `ty and configured basedpyright` -> `pass`
- `S02` `verify:` `actionlint and CI workflow contract` -> `pass`
- `S03` `M` `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py`
- `S03` `M` `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`
- `S03` `M` `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`
- `S03` `verify:` `targeted real GPU repairs` -> `pass`
- `S03` `verify:` `full lint aggregate` -> `pass`
- `S03` `verify:` `locked dependency vulnerability gate` -> `pass`
- `S03` `verify:` `dependency import audit` -> `pass`
- `S03` `A` `.vault/audit/2026-09-27-open-issues-closeout-audit.md`
- `S03` `verify:` `post-green local timing audit` -> `pass`
- `S03` `verify:` `three repaired GPU tests` -> `pass`
- `S03` `verify:` `repaired stress performance test` -> `pass`
- `S03` `verify:` `final Python lint/format, ty, configured basedpyright` -> `pass`
- `S03` `verify:` `read-only duplication and test complexity audits` -> `pass`
- `S03` `M` `.vault/plan/2026-09-27-open-issues-closeout-plan.md`

## Notes

- `S03` Prepared one-use local campaign recorder under tmp/open-issues-evidence/campaign.py. No live run started: funded TypeSafe env-file path and approval to replace the shared incompatible 0.4.35 service are pending. Draft PR #552 is the only PR for this work. Source commits: 78a6fa51 and fca45b28. Existing production release mismatch is unrepaired; no release workflow dispatched.
- `S03` User identified the funded key in main/.env and explicitly authorized managing, stopping or killing the resident GPU service, superseding competing work. Resolved key source to core main .env `(VAULTSPEC_CORE_TYPESAFE_API_KEY);` map only in process memory to rag dedicated variable. Old 0.4.35 service stopped cleanly; current checkout service startup is in progress with automatic updates disabled. No live campaign started.
- `S03` User explicitly authorized additional gated release repair workflows. Dispatched binaries.yml on main for vaultspec-rag-v0.4.35 at immutable commit 8280cc4df905b4ae7abdd739266916c2d5415fe3; run 36306076492. Local campaign remains one invocation with no retries.
- `S03` Single local campaign launched against fca45b28 with zero retries. Python lane: 5431 passed, 6 skipped, 149.35 s wall. Main GPU lane: 722 passed and three pre-existing test-contract mismatches, 1163.23 s wall. Subprocess lane continues. Offline diagnosis proves missing initial modified stamp shifts `body_line` 11 to 12 and requires metadata refresh; refreshing an existing stamp is unchanged. Targeted live verification exception requested and unanswered. Release repair 36306076492 cancelled selector job during runner setup before checkout; build jobs skipped and finalizer queued. No promotion occurred.
- `S03` User explicitly superseded the strict single-live-run constraint after the original campaign by authorizing all repairs and necessary live/integration/static verification. Preserve original red reports; bounded follow-up verification is authorized. Other session owns the five named audit commands. Five original real TypeSafe probes passed with active enrollment; original campaign ended 6228 passed, 3 failed, 6 skipped in 2886.30 s; performance unavailable at host CPU samples 31.3, 44.8, 28.7 percent.
- `S03` Authorized performance lane ran on quiet host samples 13.5, 16.0, 11.2 percent: 13 passed, one fixture failed before benchmarking because it attempted incremental indexing without a publication. Repaired setup to establish one-file canonical publication through explicit full index with declared discovery exclusions; preserve headroom and concurrent-search assertions. All 73 competing test/build processes resumed. Initial preflight failure started no performance tests and resumed all 34 build processes. Security advisory: 41 low, 30 medium, zero high, none on changed files. Dead-code advisory: one existing unused Protocol parameter.
- `S03` Original campaign remains red; user authorized repairs and targeted verification. Latest outcomes: 6245 passed, 6 accounted skips. Global 0.4.35 daemon restored. Historical release retry and full PR CI remain external gates.
- `S03` Checkpoint commit enables same-PR CI on repaired fixtures; leave S03 open until release and PR gates conclude. Eight baseline clones, one unchanged rank-D test, no changed-file findings.
- `S03` User explicitly authorized including the separate code-health cleanup in PR #552; final combined live verification waits for its committed stable source. Earlier failed CI size gate remains recorded; use its broader concurrency-test split rather than the isolated duplicate extraction.
