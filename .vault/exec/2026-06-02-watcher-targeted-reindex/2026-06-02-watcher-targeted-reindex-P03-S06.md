---
tags:
  - '#exec'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S06'
related:
  - "[[2026-06-02-watcher-targeted-reindex-plan]]"
---

# Construct the watcher's awatch with yield_on_timeout=True and an explicit one-second rust_timeout, and re-drain the pending vault and code sets on every loop iteration so an empty idle-tick batch reconciles cooldown-suppressed changes while the unchanged per-source cooldown guard still gates the actual reindex

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Add a module constant for the idle re-entry interval (one second) with a
  comment stating why the watch loop must re-enter on a timer: the pending sets
  carry cooldown-suppressed changes but are only re-examined when the loop body
  runs, and the body runs only when the watcher yields.
- Construct the watcher's `awatch` with `rust_timeout` set to that interval and
  `yield_on_timeout=True`, so the watcher emits an empty change set on each idle
  tick.
- Document at the loop head that an empty tick still runs the body, re-checking
  the cooldown and flushing any carried-forward pending set; the existing
  per-source cooldown guard and the accumulation step are left unchanged, so a
  tick reconciles only once the cooldown has elapsed.

## Outcome

The watcher now re-enters its loop on a one-second idle tick. A change suppressed
by the cooldown on an otherwise quiet tree is reconciled once the window elapses,
without waiting for a further filesystem event. The accumulation and cooldown
logic are untouched, so live-change behavior is unchanged. Verified by the
regression tests recorded under `P03.S07`.

## Notes

The pre-fix loop already re-drained both pending sets on every iteration; the
sole defect was that `awatch` never re-entered the loop on a quiet tree, so the
change is confined to the `awatch` construction plus comments. No store, indexer,
or cooldown-contract changes were needed.
