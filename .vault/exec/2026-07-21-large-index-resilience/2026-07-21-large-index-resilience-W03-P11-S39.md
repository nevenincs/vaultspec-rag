---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:ea42a072f75be614cf6cf98a64b680c4377dab65ff2a76e30cd762b618e493d0'
step_id: 'S39'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify controlled, interrupted, memory-limited, timed-out, and circuit-open jobs converge on one operator snapshot

## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

- Verify the controlled, interrupted, memory-limited, timed-out, and
  circuit-open outcomes each converge on one operator snapshot, through the
  shared parametrized resilience test
  (`src/vaultspec_rag/tests/integration/test_service_jobs.py`).
- Record that no separate test was authored, because it would duplicate the
  surfaces-by-outcomes matrix the shared test already covers.

## Outcome

The five terminal outcomes this step names each converge on one operator
snapshot, verified by the same parametrized test that verifies the sibling
surface-identity step - and no second test was written, because a second test
would assert the identical matrix.

The shared test seeds a terminal job for each outcome - controlled cancellation,
interruption, an RSS ceiling, a CUDA ceiling, a no-progress timeout, and a
watcher circuit-open - and, for each, asserts the same resilience snapshot is
reached across every operator surface: the collection route, the detail route,
the health rollup, the CLI JSON, and the CLI human render. Two axes run through
that one test. The sibling step verifies the surface axis: that the surfaces
agree for a given outcome. This step is the outcome axis: that each of the five
outcomes produces a single coherent operator snapshot rather than a
surface-dependent or outcome-dependent one. The parametrization is that outcome
axis made concrete.

The coverage is guard-proven, not assumed. Corrupting one surface's generation
identity so the state genuinely diverges turns every one of the outcome
parametrizations red, not just one; restoring it returns them all to green. So
the convergence this step verifies is real - each outcome's snapshot is asserted
equal across surfaces, and a divergence in any of them fails - across the whole
outcome set, not a single representative case.

Writing a distinct test for this step was considered and rejected. It would have
re-run the same surfaces-by-outcomes matrix the shared test already exercises,
asserting nothing the shared test does not. Redundant coverage of an identical
matrix is the kind of test the integrity mandate is against, so the honest
artifact for this step is this record documenting the shared coverage, which
keeps the decision auditable rather than leaving the step looking skipped.

## Notes

This step and its sibling surface-identity step are verified by one test,
`test_canonical_resilience_snapshot_has_http_health_and_cli_parity`. The reshape
that scoped that test to identical resilience state - excluding the broker-only
derived remediation and comparing measures at one precision - belongs to the
sibling step's record; it is the same change, and this step inherits its result
rather than adding to it.

No code was written for this step. Its deliverable is the confirmation that the
outcome-convergence property is covered and guard-proven, and the explicit
record that a separate test was deliberately not authored to avoid duplicating
the matrix.

The result is committed-HEAD's true state: the shared test was run against a
clean extract, since the working tree carries other efforts' uncommitted changes
to this file, and only the sibling step's health-parity reshape is this work's
contribution to it.
