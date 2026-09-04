---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:b738db3872e4d6fc7e5940203e211ef640c4601f379ccef3f97b9d0d0c295c1d'
step_id: 'S11'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Report environment holders as an informational readiness dimension

## Scope

- `src/vaultspec_rag/_readiness.py`

## Changes

- `M src/vaultspec_rag/_readiness.py`
- `M src/vaultspec_rag/api.py`
- `M src/vaultspec_rag/cli/_service_doctor.py`
- `A src/vaultspec_rag/tests/test_readiness_holders.py`
- `M src/vaultspec_rag/tests/test_readiness.py`

## Notes

Holders are reported beside the dependency set, not inside it. The aggregate
`ready` is `all(dependencies READY)`, so a holder node would have turned every
machine with an editor session open on its tool environment red - a fault
hunt for a healthy service. They are also not a dependency in the first place:
the reporter's own boundary is torch, models and qdrant.

A measurement changed the design mid-Step. The first version scanned on every
readiness call under a 2 second budget; the process-table walk actually costs
4.12s and 6.48s on this machine (~1700 processes), so the dimension would have
shipped permanently blind, reporting "cannot tell" every time and teaching an
operator to ignore it. The research had estimated 1-2s and flagged the figure
as inferred rather than measured, which it now is. The scan is therefore
opt-in: `server doctor` asks for it because an operator typed a diagnostic and
will wait, and the token-gated readiness route does not, because a broker polls
it. A third state, `scanned: false`, keeps "nobody asked" distinct from "held"
and from "clear".

Command lines are deliberately absent from the payload. The refusal an
operator reads locally carries them; this snapshot crosses a network, and an
argument vector can hold material nobody chose to publish.

The exact-key-set assertion in `test_readiness.py` failed on the new member,
which is that test working: the key set is a deliberate bound against the
report accreting into a general health console. It was widened with the
reason recorded rather than relaxed.

Guard proof: making the scan unconditional failed
`test_a_polled_route_does_not_pay_for_a_process_table_walk` on
`assert holders.scanned is False`. Restored; zero MUTATION markers remain.
Gates: ruff, ty, 26 readiness and holder tests green.
