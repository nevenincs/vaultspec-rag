---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:b365fcea163e611e5b95b385334a4b07e48c14a27ebf67460830ea778b0f3437'
step_id: 'S63'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Replace transaction-scoped use of raw connections with one closing accessor and repoint every read site onto it

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`

## Description

- Add handle-scoped connection and transaction helpers beside the opener.
- Repoint all eighteen read sites across the ledger mixins and the migration journal onto them.
- Delete the per-class delegating accessors and their protocol declarations, so call sites use the shared helpers directly.

## Outcome

Every ledger connection is now closed on every path. The driver's own context manager scopes a transaction rather than a handle: its exit commits or rolls back and leaves the connection open, so each read stranded a live handle until the collector happened to reclaim it.

The delegating accessors were removed rather than kept. Each had become a method whose whole body was one call into the module that owns the behaviour, which is the shape the canonical-code rule names outright.

## Notes

The delegating accessors were introduced earlier in this same phase and then removed within it, once they were seen to be exactly the one-call-into-the-owning-module shape the canonical-code rule prohibits. The retired legacy ledger filename fallback was deleted here as well.
