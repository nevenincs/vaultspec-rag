---
tags:
  - '#adr'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
modified: '2026-06-18'
related:
  - "[[2026-06-18-watcher-targeted-reindex-research]]"
  - '[[2026-06-02-watcher-targeted-reindex-plan]]'
---

# `watcher-targeted-reindex` adr: `idle-tick flush for cooldown-suppressed reindex` | (**status:** `accepted`)

## Problem Statement

Issue #192 reports that incremental reindex never evicts deleted files from the index;
only a full rebuild clears them, which is prohibitively expensive at codebase scale. The
research established that the store and the scoped indexer evict durably in both the
server and local backends — verified against the real supervised Qdrant server and the
local on-disk store. The leak is in the watcher's event loop.

The scoped-reindex feature gave the watcher a per-source cooldown plus a pending-set
carry-forward: a change that arrives during the cooldown window is held in the pending
set and merged into the next run rather than triggering an immediate reindex. The defect
is that the watcher drains the pending sets only inside the body of its
`async for changes in awatch(...)` loop, and that body runs only when the watcher yields
a non-empty change batch. A change suppressed by the cooldown is carried forward
correctly but is never re-examined until the next filesystem event arrives. With an idle
tree, the carried batch is stranded indefinitely. A deletion is the change type that
reliably has no follow-on event for its path, so deleted content is the visible symptom.

## Considerations

The watcher is built on `watchfiles.awatch`, which is constructed today with the library
default `yield_on_timeout=False` — the generator only yields when real changes occur, so
the consumer loop never re-enters on a quiet tree. The fix must restore the missing
trailing-edge flush: the last pending batch must always be reconciled even when no
further filesystem events arrive, without weakening shutdown responsiveness or the
existing cooldown's anti-thrash purpose.

Three approaches were weighed in the research. Library-native idle yield
(`yield_on_timeout=True` with an explicit `rust_timeout`) makes the generator emit an
empty change set on each idle tick, so the existing loop body re-runs and re-drains the
pending sets. An external timed flush wrapping `anext()` of the watch generator in an
`asyncio` timeout was rejected on documented grounds — PEP 789 describes exactly that
construct as a cancellation hazard, because the timeout can fire after the generator
yields but before the consumer resumes, surfacing `CancelledError` in the outer task. A
dedicated flush-timer task is cancel-safe but adds a second task touching the shared
pending state plus trailing-edge reschedule and starvation bookkeeping, and is only
warranted if the flush cadence must decouple from the watch-wait cadence — which it does
not here.

## Constraints

The decision rests on `watchfiles` 1.2.0, a mature dependency already in use; the
`yield_on_timeout` and `rust_timeout` parameters and their empty-set-on-timeout behavior
were verified directly in that version's source, so there is no frontier risk. The
behavior is platform-aware: for `awatch`, an unset `rust_timeout` resolves to 1000 ms on
Windows and 5000 ms elsewhere, and the `stop_event` is checked on every Rust wait cycle
independently of `yield_on_timeout`, so shutdown does not regress. The parent feature —
the scoped `incremental_index(changed_paths=...)` path and the pending-set carry-forward
— is stable and already shipped; this decision only changes when the carried set is
drained, not how a reconcile is computed or applied. No new dependency, schema, or
backend behavior is introduced.

## Implementation

Construct the watcher's `awatch` with `yield_on_timeout=True` and an explicit
`rust_timeout` of roughly one second, and treat an empty yielded batch as an idle tick:
the change-accumulation step becomes a no-op for an empty batch, and the pending-set
draining for both the vault and code sources runs on every iteration — real batch or idle
tick alike. The cooldown check inside the per-source processing is unchanged, so the tick
only triggers an actual reindex once the cooldown has elapsed and there is pending work;
otherwise it is a cheap pending-set emptiness check. This converts the cooldown from
"re-checked only on the next filesystem event" to "re-checked on every idle tick,"
restoring the trailing-edge flush on a quiet tree. The explicit `rust_timeout` keeps the
idle cadence the same on every platform rather than inheriting the platform-specific
default. No change is required in the store, the indexers, or the cooldown/carry-forward
contract.

## Rationale

The research grounds the choice. Option A is the minimal change that closes the leak: it
reuses the existing draining code path, adds no wakeups (the Rust thread already times out
at the `rust_timeout` cadence regardless of the flag — the flag only decides whether that
timeout yields to Python), and is the PEP 789-correct shape because the timeout lives
inside the generator's own wait rather than wrapped around `anext()` from outside. The
broader debounce literature frames the bug precisely: a trailing-edge debounce with no
independent timer strands its final batch, and the fix is to drive the trailing flush off
an independent clock — here, the library's idle tick. The rejected options are heavier
(dedicated task) or unsafe (external `wait_for(anext(...))`).

## Consequences

The watcher now reconciles a quiet tree's last pending batch within roughly one cooldown
window plus one tick, so deleted files are evicted by incremental reindex without a full
rebuild, and the symptom in #192 — and the general class of any cooldown-suppressed
change going stale on an idle tree — is resolved. The cost is one extra generator
resumption and a pending-set emptiness check per idle second, which is negligible against
the work the Rust thread already does. A subtle benefit is that the fix is type-agnostic:
adds and modifications suppressed by the cooldown on an otherwise quiet tree are flushed
by the same tick, not just deletions. The main pitfall to verify in execution is that the
idle tick does not interact badly with the per-source cooldown to cause premature or
repeated reindexing — the cooldown guard must continue to gate the actual run, and the
regression test must confirm that an idle tick during the cooldown does not itself trigger
a reindex before the window elapses. The regression guard is the real-backend
reproduction: delete a file during the cooldown window, then leave the tree quiet, and
assert the chunks are evicted.

## Codification candidates

- **Rule slug:** `watcher-flushes-pending-on-idle`.
  **Rule:** Any application-level debounce or cooldown layered on top of the filesystem
  watcher must guarantee its last pending batch is flushed on a quiet tree (e.g. via the
  `awatch` idle tick), never only on the next filesystem event.
