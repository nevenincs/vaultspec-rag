---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
body_hash: 'sha256:f59821a4fcc87df71452cc2532a840f18cdd9e7bfdb19b9340da9d7dd9d667d9'
step_id: 'S05'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]"
---

# Add a bidirectional guard test that a race-losing spawned daemon terminates instead of lingering

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

- Bind the race-losing-daemon test to the forced-exit backstop by asserting the
  witness line the backstop logs immediately before calling `os._exit`, which a
  daemon reaching a natural interpreter exit never writes.
- Assert the refusal's cause and the winning holder's pid, so an unrelated
  startup failure cannot satisfy the test and report the singleton path covered.
- Raise the exit bound from 60 to 180 seconds against the measured cold-start
  cost, and state that measurement in the constant's comment.
- Add an explicit function timeout, and comments naming the mutation each
  narrow assertion catches.

## Outcome

The test is a guard rather than a hang check, and the difference was
demonstrated rather than assumed.

Red: mutating the forced-exit helper to return unconditionally - permitting the
unguarded exit path - fails the test on the intended assertion, the one
requiring the forced-exit witness at code 1. The daemon still exited, and still
exited NON-ZERO, so both pre-existing assertions passed under the mutation. The
witness assertion is the only one that detects the backstop's removal, which is
precisely why it was added.

Green: restoring the guard leaves the source byte-identical to its committed
state and the test passes in about six seconds. Both directions ran as one
uninterrupted sequence and nothing was left mutated on disk.

## Notes

The first mutated run reported a pass; re-running the identical mutated tree
reported the failure above, and a standalone reproduction outside pytest
confirmed the mutated daemon writes no witness line at all. The likely cause is
a stale bytecode cache in the freshly spawned daemon on the run immediately
following the edit. Recorded because it bears on any future mutation proof
against a subprocess: a single green run taken right after touching the source
is not evidence, and the proof must be repeated or confirmed out of band.

The honest scope of the test is unchanged in one respect. It does not reproduce
the interpreter-exit wedge itself, which needs a non-daemon thread hung in a
blocking call, and none exists this early in startup. What it now proves is that
the daemon leaves through the path that would escape such a wedge, which is the
property the guard exists to hold.

The test carries the module's integration marker and no GPU marker: a daemon
that loses the claim refuses before any model load, so marking it as GPU work
would misreport what it costs.
