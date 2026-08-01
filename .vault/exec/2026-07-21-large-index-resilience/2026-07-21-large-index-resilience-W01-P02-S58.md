---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b443db462f20787da55a3f34030c2fe4a903deba02d6389c7e58d15c17abdf98'
step_id: 'S58'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Cover carried-forward retention end to end: index, carry a generation forward, and assert inherited points survive an incremental run

## Scope

- `src/vaultspec_rag/tests/integration/test_codebase_integration.py`

## Description

- Add a guard that publishes a generation, starts an inheriting generation from
  it, and asserts every carried-forward point is still recognised as retained
  (`src/vaultspec_rag/tests/test_index_run_ledger.py:747`).
- Assert the inheriting generation actually carried the states, so the test
  cannot pass by never reaching the condition it covers.

## Outcome

The defect now has the guard that would have caught it, and the guard was proven
against the defect rather than assumed to cover it.

Run against the unrepaired code, it fails with an empty retained set where every
inherited point was expected - not a near miss or an off-by-one, but none of
them recognised. That is the whole mechanism in one assertion: an incremental
run asks which inherited points are still retained, is told none are, and
deletes them all. The message it fails with names that consequence, so a future
reader meets the explanation rather than a bare set comparison.

The existing carry-forward coverage came close without touching it. It already
published a generation, started an inheriting one, and asserted the file states
were carried - then went on to test path deletion. What it never asked was
whether the carried states' points survive a retention check, which is the exact
question the defect answers wrongly. The new guard picks up where it stopped and
asks only that.

Setting the condition up honestly matters more than the assertion here, because
the condition is what makes the defect reachable. A full generation is indexed
and taken through every finalization phase to a published success, and only then
is the inheriting generation started, so the carry-forward is real rather than
simulated. The test asserts the parent link and the carried states before
checking retention, so it cannot quietly degrade into a test that passes because
nothing was ever inherited.

## Notes

The guard is at the ledger level, which is where the defect lives and where it
can be stated precisely. The two integration tests whose counts exposed it are
real coverage of the consequence, but they observe it only as a number that
fails to rise; neither names inherited points, so neither would have explained
the cause to whoever hit it next.

Coverage stops at the code kind, matching the repair. The document domain uses
the same ledger and the same carry-forward, so the same guard would be
meaningful there; that was not added and is an open follow-up rather than an
oversight.

No mock, stub, patch, or fake is used. The test drives a real ledger through the
real generation lifecycle.
