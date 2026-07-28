---
tags:
  - '#adr'
  - '#stdio-orphan-rearm'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-adr]]"
  - "[[2026-07-16-mcp-stdio-lifetime-adr]]"
  - "[[2026-07-28-stdio-orphan-rearm-reference]]"
---

# `stdio-orphan-rearm` adr: `re-arming the lost-anchor backstop instead of disarming it` | (**status:** `accepted`)

## Problem Statement

Two stdio servers were found resident 20.6 hours after their client and
their entire ancestor chain had exited. The watchdog was armed in that
build, so this is a gap in the fallback path, not a missing feature: with
no resolvable pipe creator the discovered chain arms grace-prunable, and
when every member dies inside the grace window the backstop disarms and
never re-arms. `2026-07-17-stdio-watchdog-convergence-adr` recorded that
disarm as a deliberate blind spot on the assumption that stdin EOF remains
as the exit path. On Windows it does not: the client's inherited write
handle routinely outlives it, so EOF never arrives and the disarm is
permanent. The fail-open policy is right when the watchdog *cannot* arm; it
is wrong when the shim can still observe that nothing is left above it.

## Considerations

- Losing every anchor is observable, and observability is what separates
  this from the cases fail-open protects: the shim can enumerate its own
  ancestry at any time without cooperation from anything.
- Re-resolving the pipe creator after startup - the obvious repair, and the
  one the report suggests first - deadlocks. A pipe query is I/O on the
  synchronous stdin file object, so once the transport's reader has a read
  pending on that handle the query blocks behind it for the life of the
  process. Measured on the target platform, not inferred.
- Snapshot enumeration needs no rights on the processes it lists, where
  opening a handle does. The two disagree exactly when an ancestor runs at
  a higher integrity level, and that disagreement must not read as
  orphanhood.
- A venv `python.exe` under uv is a trampoline that stays resident as its
  child's parent, so the direct-parent anchor in that shape is immortal.
  The reported orphans sat under `uv` wrappers that do exit independently.
- The exit event shape is shared byte-compatible with the companion core
  watchdog and cannot move.

## Considered options

- **Keep fail-open, accept the leak:** rejected - the leak is expensive
  (a rag server holds model and index state) and invisible, because the
  client that would have reported it is long gone.
- **Re-resolve the pipe creator after the grace window:** rejected on
  measurement - it hangs the watchdog thread permanently, converting a
  recoverable disarm into a silent one that also never fires.
- **Treat "no anchor at all" as fatal at arm time:** rejected - it reaps
  console runs and exotic spawners that have a working EOF path, and it
  cannot tell an unopenable ancestor from an absent one.
- **Retry arming forever, never reap:** rejected - it fixes the diagnostic
  and not the leak; a shim with nothing above it never acquires an anchor.
- **Chosen:** keep arming fail-open, but replace the permanent disarm with
  a re-discovery loop that arms on any survivor and reaps only after
  several consecutive rounds confirm no live ancestor exists.

## Constraints

- Re-discovery is ancestry-only. Nothing on the watchdog thread may touch
  the stdin handle, which rules out the pipe creator as a re-arm source
  and makes the resolver install-time and main-thread only.
- The reap is unrecoverable, so the verdict is taken over several rounds
  rather than one observation, and any contrary evidence resets it.
- Module rules are unchanged: stdlib-only, no mcp or torch import,
  stdio-branch-only install.
- POSIX is unchanged; its reparent poll already detects orphanhood.

## Implementation

The Windows wait thread splits into a grace prune, a re-arm loop, and the
wait. The prune is as before and additionally reports the nearest target it
dropped, which names the dead ancestor if the shim later reaps itself.
Where the thread previously returned on an empty survivor set, it now
loops: re-open the ancestor chain, and on any survivor arm and wait. A
re-armed target is never grace-prunable, because nothing alive that far
past startup is a transient spawn helper. When re-discovery comes up empty,
a permission-free snapshot walk decides whether that emptiness is real: an
ancestor still listed but unopenable resets the counter and holds the reap
off indefinitely, while a genuinely absent chain advances it. Reaching the
confirmation bound exits through the existing hard-exit path, so the
shared event keeps its shape.

The resolver refuses to run off the main thread, which makes the deadlock
unreachable rather than a comment. An empty target set at install time now
starts the thread instead of returning, so the orphan case is a state the
loop resolves rather than a reason never to watch. Each unanchored round
emits its own structured stderr event alongside the existing exit event,
and a failed wait emits a disarm event where it previously only logged.

## Rationale

The knockout is that the alternative repairs are unavailable or unsafe:
re-resolving the client deadlocks, and a fatal no-anchor policy reaps
sessions it cannot inspect. Re-discovery is the one signal that is both
permission-independent and free of the stdin handle, and splitting it
across the handle walk and the snapshot walk is what lets the shim tell
"cannot open" from "not there" - the distinction the reap turns on. The
cost is bounded latency on an already-eventual backstop, and the failure
direction is preserved: every ambiguous observation extends protection.

## Consequences

- An orphaned shim now reaps itself under a minute instead of persisting
  until an operator finds it; the reported accumulation class closes.
- An unanchored shim is visible on stderr while it is unanchored, which is
  what host tooling needed to detect this without a process audit.
- A shim whose ancestor slot is recycled by an unrelated process keeps the
  veto and is not reaped; over-conservative, and the safe direction.
- The convergence record's blind-spot paragraph no longer describes shipped
  behaviour and is superseded on that point.
- The companion core watchdog carries the same design and the same gap, so
  the fix is expected to land there too; the event shapes stay aligned.
