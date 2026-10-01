---
tags:
  - '#plan'
  - '#incremental-index-recovery'
date: '2026-09-30'
tier: L1
related:
  - '[[2026-09-08-incremental-publication-cost-adr]]'
  - '[[2026-09-07-explicit-reindex-authority-adr]]'
  - '[[2026-09-08-adaptive-watcher-control-adr]]'
  - '[[2026-07-25-non-destructive-index-publication-adr]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-09-01-generation-accounting-adr]]'
modified: '2026-10-01'
body_schema: body-v2
body_hash: 'sha256:d9c8b0508a87cbd3d5dbe3089d51dcc0d799cb768eb6c2982c63968d63fb5b6d'
---

# `incremental-index-recovery` plan

## Description

Approved 2026-10-01

The user explicitly authorized fixing every incremental-indexing, recovery-state and vault-audit bug identified during the storage recovery. Restore the accepted publication, explicit authority and durable watcher contracts without changing public schemas, GPU ownership or storage locking. Existing accepted decisions cover all repairs; no new costly decision is proposed.

The incremental-publication-cost decision governs receipt finalization and bounded route work in S01 and S02, and canonical verification in S04. Explicit-reindex-authority and non-destructive-index-publication govern safe receipt recovery in S01. Adaptive-watcher-control governs successful rebuild settlement in S03. Service-job-control and generation-accounting govern exact job-to-generation association and truthful source outcomes. Large-index-resilience governs genuine durable progress and real-ledger verification throughout.

## Steps

- [x] `S01` - Make no-op publication finalization idempotent and recover unfinished receipts safely for explicit rebuilds; `src/vaultspec_rag/indexer/_checkpoint_common.py, receipt and rebuild admission owners, src/vaultspec_rag/indexer/_vault_indexer.py, src/vaultspec_rag/indexer/_vault_incremental.py, receipt regression tests`.
- [ ] `S02` - Bound incremental route reconciliation and indexed ledger membership work with genuine durable checkpoints; `src/vaultspec_rag/indexer/_route_migration.py, bounded effective ledger readers, reconciliation performance tests`.
- [ ] `S03` - Settle stale watcher refusals only after certified published rebuilds, report failed generations truthfully and preserve concurrent dirty scope; `src/vaultspec_rag/watcher_retry_policy.py, src/vaultspec_rag/job_dispatch.py, watcher runtime and service settlement owners, watcher and job regression tests`.
- [x] `S04` - Validate optional and nested vault payload fields and compare canonical audit identities correctly; `src/vaultspec_rag/_index_integrity.py, payload validation owners, vault audit regression tests`.

## Parallelization

Implement S01, S03 and S04 concurrently with three delegated workers under vaultspec-team. The receipt worker owns checkpoint and receipt recovery modules and their focused tests. The watcher worker owns watcher policy/runtime and service settlement integration and their focused tests. The audit worker owns payload validation and canonical audit identity and their focused tests. The supervisor owns S02 route reconciliation and ledger query performance, shared test commands, plan/ledger writes, all commits and the integrated review. Serialize any shared source change through the supervisor. All workers share the isolated incremental-recovery worktree and must preserve other workers' edits. After S04 closes, its worker may own the disjoint S02 real-storage regression module while the supervisor retains production ownership. S02 final verification depends on S01 receipt behavior. Workers do not commit or alter vault records.

## Verification

Exercise the production finalization path for repeated empty and unchanged document updates without advancing proof revision. Demonstrate safe explicit rebuild recovery after an unfinished receipt while preserving served data and source isolation. Verify bounded page/scoped reconciliation and indexed candidate membership using real SQLite and temporary storage, with mutation-proved guards against corpus-wide incremental work and unsafe deletion. Verify that successful explicit rebuild settlement clears only obsolete watcher refusal and retains newer pending changes; unsuccessful, incremental and foreign-source jobs cannot clear it. Audit valid vault payloads including optional content and nested passages, and reject malformed payloads and foreign identities. Run relevant regression suites, package lint and formatting, strict type checks and vault checks. Record red/green guard evidence and perform the final integrated review before completion. Do not push, merge or alter the running installed service during implementation.
