---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# add unit tests covering candidate discovery, ranking, the cap, and each eligibility gate rejecting an ineligible donor

## Scope

- `src/vaultspec_rag/tests/test_donor_candidates.py` (new)`

## Description

- Add `src/vaultspec_rag/tests/test_donor_candidates.py` (23 tests, all real files in tmp, no mocks; the schema probe is a caller-seam parameter, not a patch).
- Isolate `VAULTSPEC_RAG_STATUS_DIR` and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to tmp via an autouse fixture with `reset_config()` on both edges.
- Cover discovery: self-prefix exclusion, backend filtering, kind-collection filtering via an injected manifest mapping, worktree-family sibling outranking a newer stranger (real `.git`-file/`commondir` layouts built on disk), path-family fallback ranking, newest-first ordering within a rank, and cap enforcement (default constant, custom cap, cap 0).
- Cover each eligibility gate rejecting an ineligible donor with the SPECIFIC structured reason asserted as the exact single-element `reasons` tuple, so later mutation proofs bind to the intended assertion: wrong kind, storage schema generation mismatch, dense dimension mismatch, named-vector layout mismatch, unreachable donor schema, embed-marker model-identity mismatch, content-epoch mismatch, missing sidecar, malformed sidecar, legacy sidecar missing the epoch key.
- Cover recorded-state reads for vault (round trip + missing epoch key) and document (round trip + incomplete publication fails closed) sidecars, plus a positive control where a fully eligible donor passes every gate with `reasons == ()`.
- Add a fresh-interpreter subprocess test asserting `import vaultspec_rag.indexer._donor_candidates` leaves `torch` out of `sys.modules`.

## Outcome

- `uv run --no-sync pytest src/vaultspec_rag/tests/test_donor_candidates.py -q` -> `23 passed, 1 warning in 1.64s` (re-run after formatting; first run 3.35s, same 23 passed).
- ruff check clean, ruff format clean, basedpyright `0 errors, 0 warnings, 0 notes`, ty `All checks passed!` on both new files.

## Notes

- Rejection tests assert `reasons == (EXPECTED,)` exactly (not `in`), with comments naming the comparison each assertion binds, so the planned mutate-red-restore-green proofs for the dims, model-identity, and epoch gates have unambiguous targets.
- Manifest-backed discovery tests build entries through the real `record_root` writer; only the kind-collection filter test injects a hand-built legacy-shaped `ManifestEntry` mapping, because the current writer always declares all three collections.
