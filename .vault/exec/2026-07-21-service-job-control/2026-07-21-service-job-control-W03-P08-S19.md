---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:da7024374b3d203e3287c9e31af0f32f111278b50112567c0a8a5304fc6ac9b7'
step_id: 'S19'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Keep watcher enablement separate from job cancellation and wait for manager-owned cleanup on watcher stop using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/server/_watcher.py`

## Description

- Separate public watcher enablement state from private cleanup ownership so
  stopping intake never cancels or mutates a canonical indexing job.
- Retain stopped watcher tasks until their intake coroutine and exact
  watcher-origin manager attempts release naturally under one bounded deadline.
- Keep timed-out drains retryable and serialize start or reconfigure requests
  behind the retained owner without overlapping watcher generations.
- Pass the exact rebindable service registry through watcher attempts so lease,
  indexer, graph-cache, and cleanup ownership remain on one registry instance.
- Make explicit project closure use atomic eviction and raise
  `ProjectBusyError` instead of closing storage beneath a live lease.
- Export the bounded watcher cleanup join for the following service-lifespan
  step and preserve cross-thread owner-loop scheduling.

## Outcome

Watcher stop now disables new filesystem intake immediately while leaving all
canonical job desired state untouched. Private drain state remains observable
until the intake task and every matching watcher-origin attempt release task,
worker, capacity, project lease, writer lock, and pipeline ownership. Timeout
returns truthful failure without cancelling the attempt; later ensure or
reconfigure calls reschedule the retained drain and publish at most one new
watcher generation after cleanup.

The watcher uses the exact package registry captured for its slot and managed
attempts. Explicit `close_project` signals intake first and delegates its
existence, refcount, and removal decision to `try_evict`; a live lease raises
`ProjectBusyError` and leaves its store open. Public watcher cleanup is exported
for S20 without changing shutdown behavior in this step.

Verification passed: 120 server and watcher-wiring tests; three real
`TestCloseProject` cases; one real busy-lease eviction case; 64 focused job
control and jobs tests; 42 watcher, filter, CLI, and ADR tests; Ruff, formatting,
BasedPyright, scoped complexity, and diff hygiene. Independent re-review
approved at Critical 0, High 0, Medium 0, Low 0.

## Notes

The repository-wide complexity command still reports only pre-existing blocks
outside the S19 diff; the S19 functions are below the enforced thresholds. The
live watcher-control service campaign remained blocked before watcher assertions
by the known external Qdrant authority publication and connection-refusal
baseline. No semantic-RAG rerun was attempted after the previously observed CUDA
out-of-memory condition.

No fake, mock, stub, patch, monkeypatch, skip, expected failure, canonical job
mutation, or task cancellation was added.
