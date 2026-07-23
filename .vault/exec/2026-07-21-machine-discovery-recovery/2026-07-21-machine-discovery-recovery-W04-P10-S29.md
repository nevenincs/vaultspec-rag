---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S29'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Backstop the daemon shutdown with a gated os._exit so a wedged periodic to_thread worker cannot hang the interpreter-exit executor join

## Scope

- `server/_lifespan.py`
- `server/_main.py`
- `server/_state.py`
- `server/__init__.py`

## Description

- Root-caused a shared daemon shutdown/rollback hang (three failing integration cases: a graceful mid-index stop, a running-phase status-lock rollback, and a restart) to one common wait. Every daemon exit returns normally and the interpreter-exit `concurrent.futures` thread-pool join blocks forever on a wedged periodic `asyncio.to_thread` worker (the heartbeat tick, the qdrant-liveness restart tick, or the storage-survey warmup), long after every resource is released. The rollback case proves it: the daemon logs `Service shutdown complete`, then never exits.
- Added `_exit_standalone_daemon(code)` in `_lifespan.py`: it flushes the daemon log-pipe drain (so `service.log` keeps the final shutdown lines that `os._exit` would otherwise drop) and calls `os._exit(code)`. It is gated on a new `_daemon_process` sentinel and returns without exiting when the gate is off.
- Wired two call sites: the post-yield `finally` exits `0` after the bounded clean-shutdown teardown, and the pre-yield `except` exits `1` after its teardown and before the re-raise. Placement is inside the lifespan so the exit preempts uvicorn's own loop-teardown executor join, which in this interpreter carries a multi-minute default timeout that exceeds the tests' exit deadlines.
- Added `_daemon_process: bool` and `_daemon_log_capture` holders to the server state module, exported both through the package alias, and armed them in `main()` immediately before `uvicorn.run` on the HTTP daemon path. Nothing else sets them, so the in-process embedded-reuse lifespan and every in-process test leave the gate False.

## Outcome

- The gate confines `os._exit` to the real spawned daemon. The embedded-reuse contract is preserved unchanged: with the gate off, a pre-yield startup failure still re-raises for an in-process retry, and a clean run still returns normally, so the in-process lifespan tests that drive the generator directly and assert a raised startup error keep passing (were they to hit `os._exit`, the test process itself would die rather than observe the exception).
- Exit codes match the operator contract: a clean stop exits `0`; a start-then-fail rollback exits non-zero.
- Behavioural verification (the three previously-hanging subprocess integration cases plus the embedded-reuse gate guard and the stop-path regression suite) is delegated; the record will note the measured result. The win is the daemon process exiting within a few seconds instead of the shutdown wait timing out.

## Notes

- The earlier store force-close bound in this phase is retained and correct: it bounds a genuine unbounded collection-lock acquire on the store teardown path, which is a distinct wait from this executor join. It was necessary hardening but not the cause of the shared hang, which is why bounding it alone did not clear the mid-index case.
- Follow-up left open (defence in depth, not required by this fix): the periodic `to_thread` operations could each be individually time-bounded so a worker never wedges in the first place. The `os._exit` backstop is the robust guarantee that the process exits regardless of which native call stalls.
- No test, rule seed, or rule sync was touched. Any rule amendment recognising a daemon-exit backstop as a bounded-shutdown pattern is deferred to a later curation pass.
