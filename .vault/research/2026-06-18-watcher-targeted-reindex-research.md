---
tags:
  - '#research'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
modified: '2026-06-18'
related:
  - '[[2026-06-02-watcher-targeted-reindex-plan]]'
---

# `watcher-targeted-reindex` research: `stranded pending changes on quiet trees`

The scoped-reindex feature added a pending-set carry-forward to the watcher so that
changes suppressed by the per-source cooldown are not lost: a suppressed change stays in
`pending_vault`/`pending_code` and is merged into the next run. This research investigates
a defect in that carry-forward and grounds the fix decision in external evidence. Issue
#192 reports that deleted files are never evicted from the index by incremental reindex,
only by a full rebuild. Reproduction (below) shows the store and the scoped indexer evict
correctly in both backends; the leak is in the watcher's event loop, and it strands any
cooldown-suppressed change — most visibly a deletion — until the next filesystem event.

## Reproduction and root cause

Three real-backend reproductions were run (no mocks), each driving the actual store,
indexer, and — where noted — the real `watchfiles`-based watcher:

- **Direct scoped delete in server mode** (supervised Qdrant binary, real GPU): index two
  source files, delete one, call the scoped incremental reindex over the deleted path. The
  store issues `delete?wait=true`, reports `removed=1`, and a follow-up id lookup finds no
  leftover chunks. **Passes** — server-mode deletion is durable.
- **Watcher-driven delete, cooldown clear**: start the real watcher, delete a file, poll.
  The watcher delivers the `deleted` event, routes it to the pending set, runs the scoped
  reindex, and the chunks are evicted. **Passes.**
- **Watcher-driven delete during the cooldown window, then quiet**: trigger one reindex to
  set the per-source last-run timestamp, then delete a second file inside the cooldown
  window and stop touching the tree. The deletion is delivered and added to the pending
  set, but the run is suppressed (`reindex_suppressed cooldown_remaining_seconds=4 pending_paths=1`) and **never reconciled** while the tree stays quiet. **Reproduces the
  leak.**

Root cause: the watcher drains the pending sets only inside the body of the
`async for changes in awatch(...)` loop, and that body executes only when `awatch` yields a
non-empty change batch. A change suppressed by the application-level cooldown is correctly
carried forward, but nothing re-examines the pending set until the next filesystem event
arrives. `awatch` is constructed with the library default `yield_on_timeout=False`, so an
idle tree never re-enters the loop body. The result is a hand-rolled trailing-edge debounce
with no independent timer to fire the trailing flush — the canonical way a trailing-edge
debounce strands its final batch.

Two reasons it surfaces specifically as the deletion symptom in #192. First, the per-source
last-run timestamp starts at zero, so the very first change after startup always clears the
cooldown and reconciles; stranding only bites the second-and-later change inside a cooldown
window. Second, an edit is normally followed by more edits to the same file, and each new
event re-pumps the loop and flushes the carried batch; a deletion is terminal — no further
event for that path ever arrives to re-pump the loop — so deleted content lingers until a
full rebuild. The defect is not delete-specific in mechanism, but deletion is the change
type that reliably has no follow-on event.

## External evidence on the fix options

Evidence gathered against the `watchfiles` 1.2.0 source (tag `v1.2.0`, `watchfiles/main.py`),
the official docs at watchfiles.helpmanual.io, the project's GitHub issues, and PEP 789.

### Option A — library-native idle yield (`yield_on_timeout=True`)

`watchfiles.awatch(..., yield_on_timeout=True)` makes the async generator yield an empty
`set()` whenever the Rust watcher times out with no changes (verified in `main.py`: the
timeout branch does `if yield_on_timeout: yield set()`). Consuming an empty batch re-enters
the existing loop body, so the pending set is re-checked on every idle tick rather than only
on the next real event. The tick cadence is the `rust_timeout` window. For `awatch`,
`rust_timeout` defaults to `None`, which resolves to 1000 ms on Windows and 5000 ms
elsewhere (the Windows value exists specifically so Ctrl+C stays responsive). The
`stop_event` is passed into and checked by every Rust wait cycle independently of
`yield_on_timeout`, so shutdown responsiveness does not depend on this change.

Cost: enabling idle yield does not add wakeups — the Rust thread already wakes once per
`rust_timeout` window regardless; the flag only controls whether that timeout yields to
Python or silently loops. The relevant lever is `rust_timeout` itself: a 500 ms–2 s window
is at most ~0.5–2 idle wakeups per second, each a genuine blocking sleep in the Rust thread
(not a spin). No maintainer benchmark quantifying this cost was found online; the
negligible-cost conclusion is inference from the source, but well-founded (the wait is a
real blocking sleep, and on polling backends the watcher rescans every `poll_delay_ms`
≈300 ms anyway).

### Option B — external timed flush (`asyncio.wait_for(anext(gen), ...)`)

Wrapping `anext()` of the watch generator in an external `asyncio` timeout is a documented
cancel-safety hazard. PEP 789 ("Preventing task-cancellation bugs by limiting yield in async
generators") describes exactly this: the timeout can fire after the generator yields but
before the consumer resumes it, raising `CancelledError` in the outer task where the timeout
block can no longer catch it. The PEP's prescribed shape is timeout-inside, yield-outside —
which is precisely what the library-native `rust_timeout`/`yield_on_timeout` already
implements internally. Re-implementing a timed flush around `anext()` reintroduces the
anti-pattern the PEP warns against, so Option B is rejected on documented grounds.

### Option C — dedicated flush-timer task

A separate `asyncio` task that sleeps the cooldown and flushes the pending set is cancel-safe
and avoids the async-generator hazard, but it introduces shared mutable state touched by two
tasks and the lodash-style cancel/reschedule bookkeeping (reset the trailing-flush timer on
every new batch, plus a `maxWait` to avoid starvation under continuous input). Within a
single-threaded event loop the two tasks do not truly race, but correctness then rests on
that discipline rather than on the loop being a single consumer. It is strictly more
concurrency surface than Option A and is justified only if flush cadence must be decoupled
from the watch-wait cadence.

### Cross-library guidance on the invariant

The property the fix must guarantee — the last pending batch is always flushed even if no
further events arrive — is the trailing-edge guarantee of debounce. Mature debouncers expose
an explicit flush / `maxWait` escape hatch precisely because a pure trailing-edge timer can be
stranded on quiet or starved under continuous input (lodash documents the trailing edge as
the default and `flush` as the guarantee that no final call is left unprocessed). `watchfiles`
itself embodies coalesce-then-flush in its Rust layer via `debounce` + `step` and never
strands its own batch; the application-level cooldown sits on top and reintroduces the
stranding because it gates the flush behind a second timer with no trailing tick of its own.
Both viable fixes (A and C) restore the trailing tick — A off the library's idle clock, C off
an independent timer.

### Deletion-event reliability (secondary, ruled out)

No `watchfiles` issue establishes a Windows-specific systematic drop of `deleted` events by
the default Rust `notify` backend. The closest issues are a macOS set-ordering/coalescing
artifact for create-then-delete inside one debounce window, and a Linux nested-copy gap —
neither indicates quiet-tree deletions go missing. The reproduced cooldown-suppression fully
explains #192, so backend deletion reliability is not a required part of the fix.
`force_polling` remains the documented defense-in-depth lever for network/edge filesystems.

## Recommendation for the ADR

Adopt **Option A**: construct the watcher's `awatch` with `yield_on_timeout=True` and an
explicit small `rust_timeout` (≈500 ms–1 s), and treat an empty yielded batch as a tick that
re-runs the pending-set draining for both sources. This is the minimal, PEP-789-correct
change: it converts the cooldown from "re-checked only on the next filesystem event" to
"re-checked on every idle tick," guaranteeing the trailing flush on a quiet tree without the
cancel-safety hazard of Option B or the added concurrency surface of Option C. The regression
guard is the third reproduction above (delete during cooldown, then quiet, expect eviction),
run against the real backend per the project test mandate.

## Sources

- `watchfiles` 1.2.0 source `watchfiles/main.py` (timeout/yield branch, defaults
  `debounce=1600`, `step=50`, `awatch` `rust_timeout`→1000 ms Windows / 5000 ms other,
  `yield_on_timeout=False`): https://github.com/samuelcolvin/watchfiles/blob/v1.2.0/watchfiles/main.py
- `watchfiles` Watch API docs: https://watchfiles.helpmanual.io/api/watch/
- `watchfiles` issue #110 (Windows Ctrl+C → awatch timeout default):
  https://github.com/samuelcolvin/watchfiles/issues/110
- PEP 789 (yield-inside-timeout cancellation hazard): https://peps.python.org/pep-0789/
- lodash `debounce` (trailing edge default, `flush` guarantee, `maxWait`):
  https://lodash.info/doc/debounce
- `watchfiles` issues #148 (macOS add/delete coalescing) and #294 (Linux nested-copy):
  https://github.com/samuelcolvin/watchfiles/issues/148 ,
  https://github.com/samuelcolvin/watchfiles/issues/294
