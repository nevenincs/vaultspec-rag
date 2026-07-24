---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Move the machine-singleton claim inside the lifespan startup try-guard so its failure routes through \_exit_standalone_daemon

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Move the `_claim_machine_singleton` call, and the `_DiscoveryPublisher` plus
  daemon-shutdown-hook construction it feeds, from before the lifespan startup
  guard to the top of the guarded `try`.
- Initialise `discovery` to `None` ahead of the guard so the failure branch can
  distinguish a lost claim (no lease, nothing to release) from a mid-startup
  failure.

## Outcome

A machine-singleton claim that loses the race now raises inside the guard and
routes through `_exit_standalone_daemon(1)` (the daemon's `os._exit`) instead of
escaping to uvicorn, where `uvicorn.run` returned and the interpreter-exit join
wedged the daemon alive. ruff, ty, and basedpyright clean; the server module
imports and the lifecycle-helper unit tests pass. Landed with S03 in commit
`57bdee8f`.

## Notes

Coupled with S03 - the teardown must tolerate `discovery is None` - so both land
in one commit. The bidirectional guard test (S05) proving a real race-loser
terminates is deferred to a GPU-free daemon-spawning window per the execution
sequencing.
