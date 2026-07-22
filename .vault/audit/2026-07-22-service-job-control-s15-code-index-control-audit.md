---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-W02-P05-S15]]"
---

# `service-job-control` audit: `S15 code indexing job control review`

## Scope

Reviewed the S15 additions in `src/vaultspec_rag/tests/integration/test_index_job_control.py`
against the accepted cooperative-control architecture and the production behavior in
`src/vaultspec_rag/indexer/_codebase_indexer.py`, `src/vaultspec_rag/indexer/_streaming.py`,
`src/vaultspec_rag/job_control.py`, and `src/vaultspec_rag/store.py`. The audit covered
real producer-consumer unwind, post-control write cessation, fresh-attempt convergence,
clean and scoped publication protection, resource release, runtime bounds, test isolation,
GPU and CPU-worker invariants, and the prohibition on test doubles or mirrored business
logic.

## Findings

### S15 code indexing job control review | high | Protected-publication tests do not prove metadata values are current

The shared `_assert_current_code_state` helper checks only the key set returned by
`_load_meta`, while both the clean and scoped tests rewrite content without changing any
paths. Stale hashes from the seeded attempt therefore satisfy the metadata assertion. A
regression that exits the protected span after publishing replacement points but before
writing current metadata would still raise the expected control signal and pass every
present assertion. The stored-payload marker proves point publication, but it does not prove
the metadata sidecar was updated before control delivery.

Resolution (re-review): Closed. Both protected clean and scoped replacement cases now
capture the production metadata immediately after seeding, preserve the identical expected
key set, and require every rewritten path's persisted value to differ after the expected
`PauseRequested`. The comparison is independent of the hashing implementation and fails if
control is delivered before `_write_meta` publishes the new values. Focused and static
verification remained green after the correction.

## Recommendations

Capture the seeded metadata before rewriting the code files, then assert after control
delivery that each rewritten path's metadata value changed. Prefer additionally comparing
the persisted values with independently computed source digests if an existing production
test helper already provides that oracle. Retain the current real-Qdrant payload, resource
release, stability-window, and convergence assertions; they provide strong non-tautological
coverage of the remaining S15 contract.

Resolution status: completed. No further Critical, High, Medium, or Low corrections are
recommended for S15.
