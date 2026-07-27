---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S16'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Decompose run-ledger responsibilities and migrate all direct importers after the active edit lands

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

Move run-ledger state contracts, SQLite runtime lifecycle, file-state methods,
commit-unit methods, and finalization methods into their direct owners. Migrate
all consumers and delete the former ledger module without a facade.

Verify direct imports, durable ledger behavior, checkpoint recovery, and
source-drift handling with focused real SQLite and local-Qdrant tests.

## Outcome

The former run-ledger module is removed and no importer resolves through it.
Five concrete owners preserve the `RunLedger` runtime contract and direct
value-object ownership. Fifty-three focused ledger and checkpoint tests passed;
scoped formatting, lint, and type checks passed; and the independent review
found no safety, behavior, import, or facade issue.

## Notes

This step was delayed until the active ledger edit was integrated, as required
by the plan. Validation used explicit ledger paths and did not modify unrelated
shared-worktree changes.
