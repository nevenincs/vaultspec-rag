---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:3dde918641e9f37b8d53817fd7c3afddd604bd658e8662710d2ba47745a870c1'
step_id: 'S60'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Open every run-ledger connection in write-ahead logging mode and prove the mode persists across reopen

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`

## Description

- Add one shared connection opener in `src/vaultspec_rag/indexer/_run_ledger_models.py` that requests write-ahead logging, reads the resulting mode back, and raises when the file will not hold the conversion.
- Set the busy budget once through `sqlite3.connect`, replacing the duplicated timeout and redundant PRAGMA.
- Route the ledger runtime's opens through that opener.

## Outcome

The ledger file reports `wal` on first open and on every reopen, verified against a real database on disk. A commit no longer escalates a reserved lock to an exclusive one, so a concurrent read can delay it but cannot fail it.

Requesting the mode is not enough on its own, so the opener verifies it took effect. A filesystem that silently refuses the conversion - a network mount being the usual case - now fails loudly at open instead of returning a connection that would reintroduce the starvation under load.

## Notes

The opener raises rather than degrading when the mode will not hold. That is a deliberate hard failure on filesystems - typically network mounts - where SQLite locking is already unreliable and this contract cannot be honoured.
