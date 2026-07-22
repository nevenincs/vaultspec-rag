---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Drive full indexing from deterministic ledger segments and storage-confirmed commit records

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Open a compatible full-run checkpoint before collection mutation.
- Filter deterministic file segments against storage-confirmed ledger units.
- Invoke the ledger callback immediately after each synchronous slice upsert.
- Reuse confirmed point identities when a compatible full generation resumes.

## Outcome

Full indexing now drives its bounded segment stream through one durable generation. A
compatible retry skips confirmed units, while new units advance only after storage returns.

## Notes

Focused lint and type checks passed. Runtime verification is deferred to the required phase
boundary after S25.
