---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S28'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Decide whether in-process lifespan reuse is a supported contract

## Scope

- `if so`
- `release the machine lock on a pre-yield startup failure (acquire inside the try`
- `or release-on-failure around the qdrant/model startup) - the shipping daemon already self-heals via OS release on process exit`
- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Make in-process lifespan reuse a supported contract: release the machine
  singleton lock on any pre-yield startup failure.
- Factor the lifespan startup into `_start_components` (returns the heartbeat
  task) and the teardown into `_shutdown_components`, so the whole pre-yield body
  runs under one guard without nesting the yield in a startup-only try.
- Wrap the startup, yield, and shutdown in a try whose `except BaseException`
  calls `release_machine_lock` and re-raises, covering the pre-yield failure (and
  a cancelled startup) that the post-yield finally never reaches.
- Add a regression test that drives the real lifespan with a real foreign HTTP
  holder on the configured qdrant port, forcing a genuine refuse-fast pre-yield
  failure, then asserts a fresh in-process acquire of the machine lock succeeds.

## Outcome

The machine lock no longer leaks on a pre-yield startup failure: a forced
refuse-fast leaves the lock free for a subsequent acquire, and a clean run still
releases exactly once in the post-yield teardown (release is idempotent, so no
double-release hazard). Two unit tests pass; the lifespan modules type-check and
lint clean.

## Notes

The release-on-failure guard re-raises the original exception unchanged, so the
loud, named startup-failure messages the daemon already surfaces are preserved.
The shipping daemon still self-heals via the OS releasing the lock on process
exit; this change only matters for the in-process lifespan REUSE path the
shutdown block's contract claims.
