---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:0911216d8d0a620279a364d2959548f9b8a1cf2cffc4aad075fa3c1a4eb83e28'
step_id: 'S30'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Bound the discovery-publisher guard acquisitions at shutdown so a heartbeat worker wedged mid-publish cannot strand teardown before any shutdown line is logged, and bound the pre-exit log flush

## Scope

- `server/_lifecycle.py`
- `server/_lifespan.py`
- `tests/test_machine_discovery.py`

## Description

- Identified a SECOND, distinct shutdown wait behind the daemon restart hang and the restart-half of the mid-index stop. Instrumented evidence: the mid-index stop's FIRST daemon lifecycle now logs the shutdown-complete boundary and the forced-exit marker in the same millisecond and exits cleanly, but the restart daemon logs no shutdown line at all before it hangs - the same signature as the pure restart case. The wait is therefore upstream of all shutdown logging.
- Traced it to the discovery publisher's guard. A synchronous heartbeat tick holds the publisher guard across real status-file and machine-pointer writes; the first teardown step acquires that same guard unbounded to quiesce publication. A tick wedged in slow or contended file I/O holds the guard, so teardown blocks on its very first line - before anything is logged.
- Bounded both guard acquisitions at shutdown: `quiesce` and `cleanup` now take an optional timeout, acquire the guard under it, and past the deadline proceed without the guard (quiesce sets the stop flag anyway so a later tick goes inert; cleanup runs its deletions unguarded, safe because the caller is discarding state and about to force-exit). Both stay unbounded when no timeout is passed, preserving normal non-shutdown behaviour. The teardown orchestrator passes a five-second bound to each.
- Hardened the forced-exit backstop's pre-exit log flush per the shutdown-safety invariant: the log-pipe drain is now closed on a short-lived daemon thread joined for a fixed budget, after which the process exits unconditionally. A wedged drain can no longer hold the process past the exit - the same class of wait the backstop exists to escape, which must not be reintroduced in its own flush.
- Added a guard test: a second thread holds the publisher guard and never releases within the bound; bounded quiesce returns at its deadline with the stop flag set rather than blocking to the holder's release. Reverting to the unbounded acquire makes it block and fail.

## Outcome

- The two shutdown waits are now both bounded. The forced-exit backstop escapes the interpreter-exit executor join (recorded separately); this Step closes the upstream guard wait that blocked teardown before it could even begin, and makes the pre-exit flush incapable of reintroducing an unbounded wait.
- Normal, healthy shutdown is unchanged: the guard acquisitions are bounded only when the shutdown caller supplies a timeout, and a legitimately slow tick within the bound is still awaited. The abandon-past-deadline path is reached only when a worker is genuinely wedged, and only while the daemon is discarding state to force-exit.
- Behavioural verification across the restart, mid-index-stop, and running-phase-rollback cases is delegated to the harness operator; the guard-level bound and its mutation proof are what this record confirms.

## Notes

- A self-inflicted regression was caught and fixed before it could ship: an earlier edit in this batch detached the lifespan's asynccontextmanager decorator from its function, leaving it on the exit helper instead. It happened to still force-exit (the context-manager wrapper invokes the wrapped function when constructing the manager), which masked it, but it was wrong. The decorator is restored on the lifespan and the helper is a plain function again; an import-and-signature check confirms both.
- Whether the running-phase rollback case is this same guard wait or reaches the forced-exit backstop was not separately confirmed from its log (the harness deletes the run directory before it can be grepped). Both waits are now bounded, so either classification is covered; the acceptance run will show which line it reaches.
- The discovery guard is an in-process lock, so abandoning it at shutdown risks nothing on disk beyond a racing best-effort write against a deletion, which is acceptable when the process is about to exit. No rule seed or provider mirror was edited.
