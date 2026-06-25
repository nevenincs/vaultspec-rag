---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S04'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Diagnose the reproduced server-mode leak and apply the minimal durability fix to the delete path

## Scope

- `src/vaultspec_rag/store.py`

## Description

Traced the diagnosis and durability fix for the reproduced server-mode deleted-file leak.
The root cause was not the store delete primitives - those are correct and now
server-mode-proven by the eviction tests - but the watcher loop: a deletion suppressed by
the per-source cooldown was only re-drained on a subsequent non-empty filesystem event, so
on a quiet tree the deletion stranded forever. The minimal durability fix re-arms the watch
loop on an idle timeout so the carried-forward pending set flushes once the cooldown
elapses, with no further filesystem event.

## Outcome

The step is genuinely shipped. The store-layer delete-by-filter and delete-by-id paths
durably evict against the real Rust engine (proven by the server-mode eviction suite), and
the watcher idle-flush fix closes the stranded-deletion path that left issue 192's stale
results behind on a quiet tree. The fix shipped through pull request 197 and is on the
current branch.

## Notes

No code changes in this reconciliation pass. The original durability fix landed as the
watcher idle-flush change (the loop re-enters on an idle tick rather than only on a
non-empty yield); the store delete primitives needed no change. The plan row named the
store module, but the load-bearing fix was in the watcher loop - recorded here so the
attribution is honest.
