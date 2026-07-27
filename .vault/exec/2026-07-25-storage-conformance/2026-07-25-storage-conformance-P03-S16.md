---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S16'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped

## Scope

- `src/vaultspec_rag/tests/test_server_routes.py`

## Description

Plan evidence: `2026-07-25-storage-conformance-plan` marks `P03.S16` closed for Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped.

## Outcome

Six tests over the health author and the remediation pairing.

| Mutation                            | Observed failure                  |
| ----------------------------------- | --------------------------------- |
| health drops the conformance branch | `assert 'ready' == 'degraded'`    |
| conformance family unregistered     | `assert '--rebuild' in ''`        |
| models family unregistered          | `assert '' == 'models'`           |
| finding built from an empty list    | fails on the no-finding assertion |
| reason omits the collection names   | `assert False`                    |

Restored: `6 passed`. Wider check across the identity, surfacing, serving-verdict
parity, and survey modules: `36 passed`.

Three mutation attempts stayed green before the tests were re-anchored, and each
exposed a real defect in the test rather than in the code. Two asserted family
presence, which the unclaimed sweep satisfies regardless; one asserted a family
ordering that no reachable input exercises. A guard test that cannot fail is
worse than no test, so the assertions were moved onto cause-to-command pairing,
which a mutation can actually break, and the ordering claim was withdrawn rather
than defended by an assertion that would always pass.

## Notes

Template evidence: intro_commit=2f3068c7d9236d0ef7c4a81177caabf640399f5b; template_commit=2f3068c7d9236d0ef7c4a81177caabf640399f5b:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
