---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2c679f67bc349f9411490d448d12061881bd92f2891d56fba8db37b51175334a'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W02.P06` summary

P06 completed storage-confirmed resumability across full, unscoped incremental, and scoped incremental code indexing.

- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`, `src/vaultspec_rag/indexer/_streaming.py`, `src/vaultspec_rag/indexer/_run_checkpoint.py`, `src/vaultspec_rag/indexer/_run_ledger.py`, `src/vaultspec_rag/indexer/_code_meta.py`, `src/vaultspec_rag/tests/test_index_run_ledger.py`, `src/vaultspec_rag/tests/test_run_checkpoint.py`, and `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- Created: step execution records S22 through S25 and the P06 resumable-pipeline audit.

## Description

The shared weighted pipeline now treats each deterministic file segment as one storage mutation and records its ledger unit only after storage confirms the write. Compatible attempts skip committed segments, carry complete published manifests, and reconcile path or stale deletions with canonical storage-confirmed evidence. Clean attempts resume committed work without dropping the replacement collection again.

Metadata publication streams ordered, converged file-state rows to an fsynced atomic sidecar, stamps generation and policy epochs, and publishes the generation only after replacement succeeds. Operational pipeline sizing remains part of exact attempt compatibility but no longer blocks reuse of content-compatible published manifests. Cooperative control preserves checkpointed storage rather than creating ledger-ahead-of-storage state.

## Verification

- Ruff and ty passed for the changed indexer, ledger, metadata, checkpoint, and test modules.
- The final P06 boundary suite passed 20 tests covering SQLite transaction behavior, row-wise metadata publication, exact segment resume, signature drift, full idempotence, weighted unscoped and scoped incrementals, partial-publication recovery, deletion, and the pre-finalization control edge.
- The mandatory P06 audit found one critical control rollback defect; it was fixed, covered by real store/ledger/control behavior, and re-audited with no open phase-blocking findings.
