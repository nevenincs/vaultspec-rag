---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S05'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Add the compatibility test module, mutation-prove all three guards, and reconcile the two exact-key-set assertions the new field grows

## Scope

- `src/vaultspec_rag/tests/test_service_release_compat.py`

## Description

- Add `src/vaultspec_rag/tests/test_service_release_compat.py`, covering the
  discriminator truth table, both discovery readers, the three release verdicts, and the
  presence of the release field on all four wire surfaces.
- Drive the reader tests against real files on disk through the real readers, and the
  machine-pointer test against a real OS lock lease and a real published pointer, under
  the fixture that relocates both the status dir and the Qdrant storage dir.
- Grow the exact key set asserted on the readiness report in `test_readiness.py` and on
  the launcher status write in `test_cli_service_status.py` by the one new field. Both
  assertions are deliberately exact, so each was reviewed rather than loosened.
- Widen the attach-detection tuple assertion in `test_cli_server_start.py`; the stand-in
  health responder publishes no release, which the fourth element reports as absent.

## Outcome

22 tests pass in the new module. All three guards were mutation-proved in one
uninterrupted sequence, each failing on the assertion it names and passing again once
restored. No mutation was left on disk; the restore was verified by content comparison
and by re-running each test green.

Guard one, the status-file reader's refusal. Broken by replacing the discriminator check
with an always-false branch. Failed on `assert _read_service_status() is None` with the
parsed foreign payload in place of `None`; restored, passed.

Guard two, the machine-pointer refusal. Broken the same way in the resolver. Failed on
`assert resolution.state == DISCOVERY_STATE_DEGRADED` with `'ready' == 'degraded'`;
restored, passed.

Guard three, an unconfirmed release is not a match. Broken by returning the matched
verdict where the unknown verdict is returned. Failed on
`assert verdict.verdict == RELEASE_UNKNOWN` with `'match' == 'unknown'`; restored,
passed.

Each mutation is described in a comment above the assertion it breaks, so the next
reader knows what the narrow matcher is holding and does not loosen it.

## Notes

The health-route test loads the server module and is the slowest in the module (minutes,
not seconds); the remaining tests are sub-second. No GPU test tier was run: this change
touches no compute path, and the box has a single device shared with a resident service.
