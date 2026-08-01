---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:1be957b5235225a888c9371e78def58536bb5609220589bedcd4fdc027c37fd4'
step_id: 'S45'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make singleton teardown wait for the actual lock holder

## Scope

- `real singleton and Qdrant integration fixtures with foreign-holder process regressions`

## Description

- Consolidate duplicated foreign-holder launch and teardown into one real-process test
  harness with deliberately distinct launcher and lock-owner interpreters.
- Bound readiness, preserve the reported holder identity, and signal only isolated
  test-owned control paths.
- Require positive OS-lock release before launcher exit and fixture unlink, including
  the Windows case where terminating and awaiting the launcher leaves the holder alive.
- Refuse to remove a live lock and guarantee launcher/tree reaping across readiness,
  signalling, timeout, and cleanup-error paths.
- Exercise both normal release ordering and launcher-first termination without mocks,
  fakes, stubs, patches, monkeypatches, skips, or xfails.

## Outcome

- Passed the complete adversarial singleton file twice with seven tests per run and the
  exact singleton/Qdrant segment twice with twenty-two tests per run.
- Passed seventeen related machine-lock, discovery, reclaim, and real-service lifecycle
  tests, including start, health, stop, stale-status recovery, and project isolation.
- Proved the failed-start cleanup path separately with a distinct live holder: the real
  lock became free and the test-owned launcher terminated.
- Passed Ruff, formatting, Ty, BasedPyright, all complexity gates, and independent code
  review with no remaining findings.

## Notes

- Independent review found four HIGH cleanup-path defects during development: unbounded
  readiness, error-path process leakage, a missing failed-start `finally`, and incomplete
  Windows force-reap fallback. Each was corrected and re-reviewed before closure.
- No production package behavior, dependency, lockfile, provider artifact, or release
  surface changed; the correction is confined to real integration-test lifecycle code.
