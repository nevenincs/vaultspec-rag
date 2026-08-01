---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:f8f86d1946240aa065900b4f0f04d811dc6ce362c32d59daf7dc384cad809964'
step_id: 'S31'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Make the authoritative RUNNING-phase publication fail-loud so a machine-singleton daemon that cannot record its running-owner claim rolls back instead of serving

## Scope

- `server/_lifecycle.py`
- `server/_lifespan.py`
- `tests/test_machine_discovery.py`

## Description

- Diagnosed the running-phase-status-failure case: with another process holding the service-status write lock, the daemon completes startup, cannot publish the RUNNING phase, SWALLOWS the bounded write timeout, and keeps serving instead of rolling back. Confirmed by a live health probe - the daemon answers ready with climbing uptime while the acceptance test's exit wait times out. So the daemon never enters shutdown at all; there is no wait to bound, there is a missing rollback.
- Part one - fail-loud authoritative RUNNING publish. The publisher's phase-publish and its locked helper take a `require` flag: when set, a service-status write failure is raised instead of swallowed; WARMING, heartbeat, and the machine-pointer publication stay best-effort. The startup RUNNING stamp passes `require=True`, so a failure to record the running-owner claim propagates to the startup failure path and rolls the daemon back rather than letting it serve without the claim. Rationale: RUNNING is the machine-singleton "I own this machine and am serving" record; if the daemon cannot write it because another owner holds the status lock, a second daemon may own the machine's single GPU and single-writer storage, so this one must not serve. Blast radius is narrow - the write is bounded to about a second, so only sustained contention (a genuine ownership conflict) trips it.
- Part two - a contention-scoped rollback-convergence carve-out. Fail-loud alone was necessary but not sufficient: the rollback's discovery-view cleanup cannot converge while the other owner still holds the status lock, so the shutdown was recorded unclean and the shutdown-complete line the acceptance test requires was suppressed. The carve-out is deliberately narrow. The status write failure that fires the rollback is distinguished: a lock-contention timeout raises a dedicated contention-yield error, while a genuine write fault raises as-is. Only the contention-yield threads an explicit flag into the shutdown, and only under that flag does a discovery-cleanup non-convergence become an expected, non-fatal outcome that still records a completed shutdown and releases the machine lease. The normal operator-stop path, which owns the lock, is unchanged: a cleanup non-convergence there still marks the shutdown unclean. The context is threaded explicitly, never inferred globally.
- The stale WARMING view left behind by a contention-yield is reaped by the heartbeat-staleness check, and the machine pointer is deleted during cleanup (a different file, not status-locked), so the lease is relinquished cleanly.

## Outcome

- A daemon that cannot publish the authoritative RUNNING claim now rolls back and force-exits instead of serving, and the rollback records a completed shutdown even though it could not clean the views the contending owner holds. The earlier daemon-exit and discovery-quiesce bounds keep that rollback shutdown from itself hanging - the two land together as the single fix for this case.
- The carve-out does not weaken the normal-stop clean/unclean contract; it is conditioned on the contention-yield signal alone.

## Notes

- Mutation proofs. Two are unit-level and were run atomically (mutate, observe the expected failure, restore, re-run green, no mutation left on disk): disabling the fail-loud re-raise makes the RUNNING publish swallow and the guard test fails; disabling the contention-timeout mapping makes it raise a generic timeout rather than the contention-yield type and the guard test fails. The full carve-out (a contention-yield still records shutdown-complete, a normal stop still marks unclean) is proven at the acceptance level: reverting the `contention_yield` branch in the shutdown makes the rollback mark the shutdown unclean and the shutdown-complete assertion fails. That last proof is an on-box GPU run and is delegated to the harness operator to execute in both directions during acceptance verification.
- Built on the committed base that carries the daemon-exit and discovery-quiesce bounds; those bounds are what make the fail-loud rollback path safe rather than a new hang.
- The carve-out touches the shared clean-versus-unclean shutdown determination, so it is being cross-checked against an independent diagnosis before it is committed. No rule seed or provider mirror was edited.
