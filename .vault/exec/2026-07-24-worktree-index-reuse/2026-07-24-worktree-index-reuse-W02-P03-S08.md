---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S08'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# implement the backend-aware batch retrieve-by-id-with-vectors donor read path in the store layer (server mode cross-namespace

## Scope

- `local mode same-process handles only)`
- `src/vaultspec_rag/store.py`

## Description

- Add `DonorPoint` frozen dataclass to `src/vaultspec_rag/store.py`: dense vector, optional sparse indices/values, stored payload.
- Add `VaultStore.supports_donor_reads(donor_collection)`: server mode reads any collection on the shared server; local mode only the handle's own three open collections.
- Add `VaultStore.retrieve_donor_points(donor_collection, chunk_ids)`: read-only retrieve-by-string-id, ids hashed through the existing stable point-id scheme, paged in 256-id batches, dense/sparse named-vector layout decoded, misses silently absent.
- Add `_retrieve_donor_batch` (treats a vanished donor collection as an empty batch: HTTP 404 in server mode, local not-found `ValueError`; other errors propagate through the retried read path) and `_donor_point_from_record` (requires the named dense vector; sparse accepted in model and dict form).
- Respect backend-aware lock discipline: batches take the donor collection's own lock in local mode, no point lock in server mode, no store-wide mutex; no writes, no lifecycle actions, no torch.
- Add `src/vaultspec_rag/tests/test_store_donor_reads.py`: 8 tests against the real embedded backend in tmp, no mocks.

## Outcome

API:

- `supports_donor_reads(donor_collection: str) -> bool`
- `retrieve_donor_points(donor_collection: str, chunk_ids: Sequence[str]) -> dict[str, DonorPoint]`
- `DonorPoint(dense: list[float], sparse_indices: list[int] | None, sparse_values: list[float] | None, payload: dict[str, Any])`

Test results: 8/8 passed (`uv run --no-sync pytest src/vaultspec_rag/tests/test_store_donor_reads.py`): exact dense round-trip, exact sparse indices/values round-trip, payload content round-trip, absent-id misses, dense-only points report `None` sparse, missing donor collection returns empty, local-mode foreign collection unsupported and empty, empty batch, 300-id request spanning two retrieve pages plus interleaved misses.

Guard-test red/green proof (local-mode capability gate): mutated `supports_donor_reads` to return `True` unconditionally in local mode; the foreign-collection test failed on the intended assertion (`assert True is False` at the `supports_donor_reads` check); restored the gate; the full module went green again (8/8). Both directions observed in one uninterrupted sequence on 2026-07-24.

Lint/type: `ruff check` clean, `ruff format` clean, `basedpyright` on both touched files 0 errors, `ty check` has zero diagnostics in touched files (7 pre-existing diagnostics belong to `src/vaultspec_rag/indexer/_streaming.py`, owned by concurrent work). Cyclomatic complexity of the new blocks: worst rank C (`_donor_point_from_record`, CC 13), within the max-absolute-C gate.

## Notes

- Backend discovery: the embedded local engine persists cosine dense vectors unit-normalized and returns that normalized form on retrieve-by-id, so a local read may return the normalized image of the upserted vector (equivalent under cosine scoring). The tests therefore use exactly unit-norm float32-exact vectors (four 0.5 entries) so the round-trip is bit-exact. Server-mode qdrant returns vectors as stored. Named sparse vectors come back on retrieve as the client `SparseVector` model (`.indices`/`.values`); the decoder also accepts the plain dict form.
- Diff footprint kept strictly additive: new dataclass, new constant, one import line, one `__all__` entry, and appended methods; no existing method bodies touched and `_streaming.py` untouched.
- `xenon` CLI crashes on this repo's `pyproject.toml` (known); complexity measured through the radon API instead.
