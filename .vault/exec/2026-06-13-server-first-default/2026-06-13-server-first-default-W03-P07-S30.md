---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S30'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add unit tests asserting the readiness snapshot is bounded and read-only across the three dependency dimensions

## Scope

- `src/vaultspec_rag/tests/test_readiness.py`

## Description

- Add a new unit test file `tests/test_readiness.py` exercising the real readiness computation against the real environment with no mocks, patches, fakes, stubs, or skips.
- Assert the snapshot is bounded: exactly the three known dependency dimensions in a stable order, each carrying a bounded status, round-tripping through `json.dumps`.
- Assert the torch dimension reports real CUDA availability on the dev GPU and that the computation forces no model load (CUDA memory unchanged across the call).
- Assert the models dimension probes each configured repo with boolean presence, and the qdrant dimension reports the correct resolution source across the temp-isolated managed dir, the local-only backend, and an operator-supplied env binary.
- Assert the read-only contract: computing readiness writes nothing into the isolated managed dir and is stable across repeated calls.

## Outcome

- 16 tests pass. `ruff check` and `ruff format --check` are clean on the new files, and the whole-tree `ty check src/vaultspec_rag` passes.

## Notes

- The CUDA-available assertion is a real expectation on the always-present RTX 4080, not a skip condition. Side-effect-only fixtures use `@pytest.mark.usefixtures` to stay clean under the test tree's strict unused-argument lint.
