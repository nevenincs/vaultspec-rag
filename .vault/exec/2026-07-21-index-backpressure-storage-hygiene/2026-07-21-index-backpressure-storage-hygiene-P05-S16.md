---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S16'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# pass tuned wal_config and optimizers_config at collection creation to shrink per-namespace preallocation

## Scope

- `src/vaultspec_rag/store.py`

## Description

Settled the claim conflict empirically: an isolated throwaway qdrant
(pinned 1.18.2 binary, short-path storage to dodge the Windows gridstore
long-path fault) measured a fresh EMPTY namespace pair (vault + code
collections, production schema) at ~1217 MiB with server defaults - WAL
prealloc plus one segment per CPU - confirming preallocation is real for
empty namespaces (the sibling PR's "real indexed content" finding applies
to content-bearing leaks; both are true). Tuned candidates: aggressive
(wal 4 MiB / 1 segment) ~152 MiB; adopted moderate (wal 16 MiB / 2
segments) ~336 MiB, a 72% cut with ingest and intra-collection search
headroom intact. `_ensure_collection` now passes the tuned
`wal_config`/`optimizers_config` in server mode only.

## Outcome

Committed within the P05 storage commit; verified by measurement and the
existing collection-creation suites.

## Notes

Existing fat collections are left alone - auto-prune plus the ephemeral
tier retire the empties.
