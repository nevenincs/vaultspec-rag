---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:4f560450dfd2e4adcd26ccbe5ec3e842f3b9be53c607fd54ad7c66a0a6dae9a9'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W06.P16` summary

## Description

Restored the durable-state concurrency contract on the shared per-root ledger.

One opener now serves both durable databases: it requests write-ahead logging, verifies the mode took effect, and sets the busy budget once. Under a rollback journal a commit had to escalate a reserved lock to an exclusive one, which no reader can be holding, so any read outlasting the budget failed an unrelated writer's commit instead of delaying it - and because a root's ledger is shared by every content kind, that starvation crossed content kinds.

The full-database integrity scan came off the open path, where its cost tracked total ledger size across every kind and it held a read lock throughout. It is now an explicit verification entry point called from the shared resume path, and only when a generation already carries committed units - the one moment durable state is trusted to skip storage work. Fresh runs pay nothing, and the existing fail-closed corruption cases still pass.

All eighteen read sites moved onto handle-scoped helpers, so connections are closed rather than stranded until collection. The per-class delegating accessors were deleted rather than left in place, along with the retired legacy ledger filename fallback.

Artifacts: `src/vaultspec_rag/indexer/_run_ledger_models.py`, `_run_ledger_runtime.py`, `_run_ledger_commits.py`, `_run_ledger_files.py`, `_run_ledger_finalization.py`, `_route_migration.py`, `_checkpoint_common.py`.

Safety: lint, format, and type checks clean on every changed file; 211 tests green across the ledger, checkpoint, store, epoch, jobs, and regression suites. Removing the legacy filename fallback is a deliberate behaviour change - a root still carrying the old per-source ledger name will start a fresh ledger and reconcile once rather than resuming from it.
