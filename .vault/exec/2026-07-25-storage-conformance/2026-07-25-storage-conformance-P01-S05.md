---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:8eed2eb6f52b11e2a5d9875867c228e39b824989ebdcde80f283a0caf120b626'
step_id: 'S05'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Cover the preserve with a guard test, and prove it fails when the overwrite is restored

## Scope

- `src/vaultspec_rag/tests/test_storage_manifest.py`

## Description

Covered the preserve, the rekey carry, and the verdict rules with guard tests,
then put every one of them through the failure proof the guard-test obligation
requires: mutate the guard so the forbidden thing is permitted, run the test
alone, require it to fail on the intended assertion, restore, require green.

The mutations were applied by a script that restores the original file in a
`finally` block, so no weakened check could survive a failure or an interruption.
All eight ran and were restored in one sequence.

## Outcome

Ten tests, all green when unmutated. The proofs:

| Mutation                                      | Test                             | Observed failure                         |
| --------------------------------------------- | -------------------------------- | ---------------------------------------- |
| `record_root` restamps the current generation | preserves a stale schema version | `assert 2 == 1`                          |
| `record_root` drops the identity map          | preserves stamped identity       | `assert None is not None`                |
| `rekey_prefix` restamps the generation        | rekey carries identity           | `assert 2 == 1`                          |
| unstamped scores as conforming                | unstamped is unverifiable        | `assert 'conforming' == 'unverifiable'`  |
| dense-model comparison removed                | same-width swap is nonconforming | `assert 'conforming' == 'nonconforming'` |
| width branch marked non-fatal                 | width disagreement is fatal      | `assert False`                           |
| local branch routed into the manifest         | local writes no manifest entry   | prefix present in manifest               |
| sidecar written from a fresh dict             | second stamp preserves the first | `assert None is not None`                |

Restored: `10 passed`.

**One guard was inert and the proof is what caught it.** The first version of
the stale-version test called `record_root` a second time with no `last_indexed`
stamp. `P01.S04` had removed `storage_schema_version` from the idempotence
comparison - correctly, since the entry now inherits it - which meant the
mutated code short-circuited and returned the existing entry unwritten. The test
passed with the guard removed: it was exercising the no-op path, not the
overwrite. Passing a stamp forces the write path, which is also the path every
real index run takes, since each one stamps `last_indexed`. After the fix the
mutation fails as intended.

This is the whole argument for the obligation. The test named the right
property, asserted the right value, and was green in both directions; only
running it against a broken guard showed it was not connected to anything. A
comment on the assertion now names the stamp requirement so a later reader does
not remove it as redundant setup.

## Notes

Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
