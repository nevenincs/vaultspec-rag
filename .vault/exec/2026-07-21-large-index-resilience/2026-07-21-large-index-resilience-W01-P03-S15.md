---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S15'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Persist watcher retry, circuit, and convergence state

## Scope

- `src/vaultspec_rag/watcher_retry.py`
- `src/vaultspec_rag/tests/test_watcher_retry.py`

## Description

- Store one bounded retry-state document per canonical root and source.
- Serialize transitions across threads and processes with one deadline covering
  the per-path thread lock and cross-process file lock.
- Persist failure classification, exponential retry deadlines, circuit state,
  convergence generations, and active process identity.
- Track which generation one live watcher can cover with exact in-memory paths;
  promote every externally authored pending generation to unscoped convergence.
- Recover abandoned process attempts without reclaiming a live writer.
- Require unscoped convergence whenever restart loses the volatile exact-path set.
- Write a unique bounded recovery marker when cancellation cannot acquire the
  state lock within its settlement deadline.

## Outcome

Watcher intent and retry authority now survive service restart. Only timeout and
unavailable failures use closed-state retry; admission, disk, memory, schema,
and other non-retryable failures open the circuit immediately. Retry delay is
exponential, jittered, and capped, including recovery from a process that died
with an admitted attempt. A newer convergence generation cannot be cleared by
an older success.

Twenty-five focused tests passed against real files, locks, processes, and process
identity. Policy construction and every state transaction invoked by the
watcher run on worker threads, so lock polling and durable writes do not block
the service event loop. Only explicit transient lock and filesystem outcomes
retry; permanent state-path and lock-file failures fail closed. Cancellation
gives the current retry sequence a three-second settlement window, then waits
at most two seconds for a unique recovery marker outside the contended state
lock. The marker carries an authority and unique claim fence, so the next
policy owner clears only the abandoned claim it names while preserving any
newer live attempt. Markers become discoverable only after a non-globbed
temporary file is flushed and atomically replaced; transient marker I/O retries
inside the handoff deadline. A live unmatched claim fence stays discoverable
until its exact in-flight admission consumes it. Admission reservation and
policy ownership publish atomically before work moves to a native thread. A
marker either cancels a reserved admission before it starts or fences an active
one. A bounded in-process token registry distinguishes an active native
admission from a completed stale fence; after process death the next owner may
also consume it. Ruff and strict type checks passed. The state schema is
intentionally current-only; no backward-compatibility parser or fallback
authority was added.

## Notes

The state document is capped at 16 KiB and written with file durability before
atomic replacement. Parent-directory durability is attempted on POSIX and
skipped on Windows, where opening a directory as a file descriptor is not a
portable operation. Non-discoverable marker temporaries are removed only after
a persisted filesystem timestamp proves a continuous one-hour grace window;
each cleanup pass scans at most 1,024 entries and retained-live count is capped.
