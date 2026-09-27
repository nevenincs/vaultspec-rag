---
tags:
  - '#plan'
  - '#open-issues-closeout'
date: '2026-09-27'
tier: L1
related:
  - '[[2026-09-21-typesafe-classifier-adr]]'
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-09-23-status-messages-adr]]'
  - '[[2026-06-01-module-split-adr]]'
modified: '2026-09-27'
body_schema: body-v2
body_hash: 'sha256:b671034477f1d3898bdd4474e9c66bf8b5ab16ae79a691656c77c952833d1df7'
---

# `open-issues-closeout` plan

## Description

Approved 2026-09-27

The user authorized all three open GitHub issues in one PR and exactly one complete local live campaign after implementation, with timing evidence audited after green. Earlier merged PR #548 already contains the primary fixes. This follow-up covers the remaining checksum uniqueness gap, model-facing punctuation normalization, and executable documentation regression coverage. Existing accepted hosted-classification, binary-release and operator-vocabulary decisions govern; no new protocol, persisted schema, or dependency is introduced.

After that campaign exposed three existing integration-test contract mismatches, the user explicitly authorized fixing all failures and completing live, integration and static verification. S03 corrects the progress guard and stamp-refresh fixture against existing production behavior. Preserve the original campaign reports and record subsequent verification separately. The user separately authorized the gated historical release repair. Another session owns `just audit-duplication`, `just check-complexity`, `just check-nesting`, `just audit-complexity` and `just health-report`; consume their results without editing those commands.

The user subsequently authorized including the other session's complete code-health cleanup in the same PR #552. Its implementation and maintainability findings remain owned by the code-health-cleanup plan and audit. S03 owns final combined verification after that session commits a settled source tree, preservation of these issue regressions across the refactors, timing capture and post-green audit, and publishing the combined result in the existing PR. Necessary live verification is covered by the user's explicit instruction to fix all failures and pass live, integration, type, import and audit checks. Preserve every earlier raw attempt; no report is overwritten or relabeled green.

## Steps

- [x] `S01` - Sanitize model-facing text and cover content-rejection recovery; `src/vaultspec_rag/search/_typesafe_transport.py, src/vaultspec_rag/tests/test_typesafe_transport.py`.
- [x] `S02` - Require exact package checksum coverage and validate troubleshooting commands; `.github/workflows/publish.yml, tools/binaries/tests/test_release_workflow.py, src/vaultspec_rag/tests/integration/test_service_jobs_cli_basics.py`.
- [x] `S03` - Repair campaign-discovered test contracts, verify live coverage, audit timing evidence, and finish one pull request; `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py, src/vaultspec_rag/tests/integration/test_vault_true_incremental.py, src/vaultspec_rag/tests/integration/test_server_index_concurrency.py, src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py, combined src/tools/dev verification, .vault/audit/, .vault/exec/`.

## Parallelization

Execute serially in this worktree. Finish both implementation Steps before the single live campaign; offline guard mutation checks may run first. Commit completed Steps after their covering checks pass. Create exactly one PR and do not merge it.

## Verification

Run explicit Python lint, format, type and workflow checks. Prove changed guards fail on their named mutations and pass after restoration. Run one local campaign from the settled tree, preserving commands, source digest, environment facts, exit codes, wall times, per-test phase durations and outcome counts. Audit slow tests and all skips or failures after the green signal before reporting completion. Historical PyPI/GitHub repair requires a reviewed release operation; do not bypass the archive and acquisition gates.
