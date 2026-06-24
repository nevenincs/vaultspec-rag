---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S17'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Make server start detect an existing healthy machine service and refuse with a pointer

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Resolved the layering gotcha first: moved the machine-lock primitive to a neutral leaf
  `src/vaultspec_rag/_machine_lock.py` (depends only on config + `qdrant_runtime._resolve.pid_alive`),
  re-exported from `cli/_process.py` so both the CLI and the daemon import it without a
  `server` <-> `cli` cycle. Added `machine_lock_live_holder`.
- Wired the CLI pre-flight refusal in `server start` (`cli/_service_lifecycle.py`): a live
  machine-lock holder on any port/status-dir refuses a second daemon with a pointer.
- Wired the authoritative acquire/release into the daemon lifespan (`server/_lifespan.py`):
  `_claim_machine_singleton()` acquires before committing GPU or spawning Qdrant; release runs
  in shutdown after Qdrant teardown.

## Outcome

The machine singleton is enforced end to end: a fast CLI refusal plus a race-safe daemon
acquire. `ruff` and `ty` pass; import smoke confirms no cycle. Verified under concurrency by
the W04 adversarial race (S22).

## Notes

A startup failure BEFORE the lifespan `yield` does not run the release; the lock is left with
the failed daemon's (now-dead) pid and reclaimed by the next start - consistent with the
crash-safe design. Making that release immediate is tracked as `W04.P09.S28`. Extracted
`_claim_machine_singleton` to keep `service_lifespan` under the max-statements ratchet.
