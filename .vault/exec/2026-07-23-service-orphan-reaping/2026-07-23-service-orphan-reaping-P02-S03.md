---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S03'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Make the release-on-failure teardown tolerate a claim that produced no lease

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Guard the failure-branch `_shutdown_components` call with
  `discovery is not None`, so a claim that lost the race (no discovery built)
  skips a teardown that has nothing to release.

## Outcome

The failure path now falls straight through to `_exit_standalone_daemon(1)` when
the claim itself lost, and still runs full component teardown when a later
startup step failed after the lease was held. Type-checkers accept the
`_DiscoveryPublisher | None` narrowing across the guard and the post-yield
finally. ruff, ty, basedpyright clean. Landed with S01 in commit `57bdee8f`.

## Notes

Necessarily coupled with S01: moving the claim inside the guard is only correct
once the teardown tolerates a no-lease claim.
