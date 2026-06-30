---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Remove redundant bulk-delete before drop_table / drop_code_table

## Scope

- `src/vaultspec_rag/store.py` — `drop_table()` and `drop_code_table()`
- `src/vaultspec_rag/tests/test_store.py` — new `TestDropTable` class (6 tests)

## Description

`drop_table()` and `drop_code_table()` each called
`self.client.delete(points_selector=models.Filter())` immediately before
`self.client.delete_collection(...)`. The bulk delete is O(N) in the number of
stored points, holds `_client_lock` for its full duration, and is entirely
redundant because `delete_collection` unconditionally removes the storage
directory. On a 100k-point collection the extra call added several seconds of
latency under the writer lock for zero benefit.

**`drop_table()` change:** removed the `client.delete(points_selector=models.Filter())`
call and its surrounding `_suppress_local_qdrant_warnings` context. The
`delete_collection` is now the sole destructive call, wrapped in
`_suppress_local_qdrant_warnings` so any "local mode not recommended" warning
emitted by Qdrant on the delete is suppressed consistently. The
`_vault_ensured = False` reset and the `collection_exists` guard are preserved
unchanged. The now-unused `from qdrant_client import models` import inside the
method was removed as well.

**`drop_code_table()` change:** same transformation applied symmetrically.

## Tests added — `TestDropTable` (unit-marked, real local Qdrant, no mocks)

| Test                                                    | Assertion                                                                                      |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `test_drop_table_removes_vault_collection`              | After `ensure_table()` + `drop_table()`, collection absent and `_vault_ensured` False          |
| `test_drop_table_idempotent_on_missing_collection`      | `drop_table()` on a never-created store does not raise                                         |
| `test_drop_table_then_recreate_works`                   | `ensure_table()` after `drop_table()` recreates collection with count 0                        |
| `test_drop_code_table_removes_codebase_collection`      | After `ensure_code_table()` + `drop_code_table()`, collection absent and `_code_ensured` False |
| `test_drop_code_table_idempotent_on_missing_collection` | `drop_code_table()` on a never-created store does not raise                                    |
| `test_drop_code_table_then_recreate_works`              | `ensure_code_table()` after `drop_code_table()` recreates collection with count 0              |

All six tests use a real `QdrantClient` via `VaultStore(tmp_path)`. No GPU
embeddings are required — `count()` / `count_code()` against an empty collection
suffice to verify the recreate path.

## Outcome

- `ruff check` clean on both files.
- `ty check` clean on both files.
- 6/6 new unit tests pass (`pytest TestDropTable -v`, 1.06 s total).

## Notes

The `_suppress_local_qdrant_warnings` wrapper is retained on `delete_collection`
because Qdrant's local client may emit "Local mode is not recommended" on any
collection operation once a collection grows large; suppression prevents spurious
log noise during clean-rebuild flows.
