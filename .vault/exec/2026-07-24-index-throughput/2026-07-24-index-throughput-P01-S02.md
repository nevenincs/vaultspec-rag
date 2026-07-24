---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S02'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# add admission-gate tests including the mutation proof: bypass the gate, the concurrency assertion goes red on the intended assertion, restore green, both directions recorded

## Scope

- `src/vaultspec_rag/tests/` job-control suite`

## Description

Admission-gate guard tests (`tests/test_jobs_unit.py::TestEncodeAdmissionGate`, commit `e101e419`) through the real dispatch path with instrumented fake-encode runners: at most one encode job in flight; the second job is RUNNING-but-unadmitted with a measurable admission wait; the encode-bearing predicate exemptions hold; capacity-1 is reported; a source scan keeps maintenance and search modules off the limiter. Mutation proof, one uninterrupted sequence, re-proven on CPython 3.13 after the worktree venv rebuild: `_attempt_limiter` mutated to hand encode jobs the general index limiter -> `test_two_concurrent_encode_jobs_serialize_on_the_slot` failed on the intended assertion (`DID NOT RAISE TimeoutError` - the second job was admitted while the first held the slot); mutation reverted -> the full five-test class passed; working tree confirmed byte-identical after revert. Both directions recorded in the test commit body. Post-rebase obligation: this proof must be re-run after the branch rebases onto main.

## Outcome

## Notes
