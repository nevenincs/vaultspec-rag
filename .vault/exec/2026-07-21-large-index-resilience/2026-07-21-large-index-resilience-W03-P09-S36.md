---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S36'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify jobs, health, and CLI surfaces expose identical resilience state and typed outcomes

## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

- Reshape the health-parity assertion to compare resilience STATE across the
  surfaces, excluding the broker-only derived remediation, and rounding the
  measures to one precision so the comparison is of state, not serialization
  cadence (`src/vaultspec_rag/tests/integration/test_service_jobs.py:2604`).
- Verify the job response's remediation separately as the correct derivation of
  the terminal outcome all surfaces share.
- Add the shared-state projection helper and the remediation import
  (`src/vaultspec_rag/tests/integration/test_service_jobs.py:46`).

## Outcome

The jobs, health, and CLI surfaces are verified to expose identical resilience
state, with the one intended difference between them asserted rather than hidden.

The verify failed at first, and correctly. It asserted the health rollup and the
job response were byte-identical, and they were not: the job response carries a
derived remediation hint that health does not. That difference is by design -
the broker-facing response derives an action from the terminal outcome because a
broker needs one, while the health rollup is a liveness probe that stays bounded
and does not. A byte-compare across a designed difference was the wrong contract
for a step that verifies identical STATE.

The reshape scopes the identity to state without weakening it. The full
canonical field set - generation, checkpoint counts, circuit, deadline,
ceilings, profile, and terminal outcome - is asserted equal across the surfaces;
any divergence in those still fails. Only remediation is set aside from the
identity, and it is not dropped but verified in its own right: the job
response's remediation must equal the shared terminal outcome's derived remedy,
so the surfaces are proven consistent - same state, same derivation - without
forcing the health probe to carry a field it has no reason to.

The latent precision divergence is closed in the same change. The response
rounds its measures to operator precision while the health rollup projects them
at full snapshot precision; this test's values happened to be whole numbers, so
the divergence did not surface here, but a fractional-memory scenario would have
reintroduced it. The comparison now rounds both sides to one precision first, so
the identity is of state rather than of serialization cadence and cannot break
on a future fractional value.

## Notes

The reshape is scoping to state, not relaxing to green, and that was proven
rather than asserted. Corrupting one surface's generation identity so the state
genuinely diverges turns the verify red across every parametrization; restoring
it returns it to green. So the identity still catches a real state divergence -
it was narrowed to exclude a designed presentation difference, not loosened to
accept disagreement.

This result is the true committed-HEAD state: the verify was run against a clean
extract, because the working tree carries other efforts' uncommitted changes to
this file. One such change sits in an unrelated test earlier in the file and is
not part of this step; only the health-parity helper and its import are this
step's work, and they are far from that stray hunk. The commit for this step
must take only those hunks.

No product code changed - the health rollup was deliberately not edited to carry
remediation, which would have widened a bounded liveness surface to satisfy a
byte-compare. The same state-not-presentation principle carries to the operator-
snapshot convergence verify that follows.
