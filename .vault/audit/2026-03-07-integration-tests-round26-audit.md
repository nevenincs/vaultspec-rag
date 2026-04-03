---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# Round 26 Audit -- Integration Tests Coverage

Scope: all 9 test files in `src/vaultspec_rag/tests/integration/` plus `integration/conftest.py` and parent `tests/conftest.py` fixtures.

## Happy-Path Coverage Assessment

### 6 Critical Scenarios

| Scenario              | Covered? | File(s)                                                                     | Notes                                                                                                                                              |
| --------------------- | -------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Index vault (full)    | YES      | `test_indexer_integration.py:18-29`, conftest `_build_rag_components`       | Tested via session fixture + result assertions                                                                                                     |
| Index codebase (full) | YES      | `test_codebase_integration.py:75-102`                                       | Full index with real Python source files                                                                                                           |
| Search vault          | YES      | `test_search_integration.py:17-87`, `test_quality.py`                       | Multiple queries, filters, edge cases                                                                                                              |
| Search codebase       | YES      | `test_codebase_integration.py:133-167`                                      | Search with and without language filter                                                                                                            |
| Incremental update    | PARTIAL  | `test_indexer_integration.py:31-45`, `test_codebase_integration.py:105-130` | Vault incremental tested but only no-change case. Codebase incremental tests add-file case. Neither tests modify-existing-file or delete-file case |
| Delete documents      | NO       | (missing)                                                                   | `store.delete_documents` has ZERO tests anywhere. `delete_code_chunks` tested only in `test_store_codebase.py` (unit-level, outside integration/)  |

## Fixture Issues

### R26-M1: Session-scoped `rag_components` fixtures never call `store.close()` (Major)

Both `rag_components` (conftest.py:131-146) and `rag_components_full` (conftest.py:149-165) teardown with `shutil.rmtree(db_dir)` but never call `components["store"].close()` first. On Windows, the Qdrant client holds file locks on the `.qdrant-fast/` and `.qdrant-full/` directories. Calling `shutil.rmtree()` while locks are held can raise `PermissionError`, causing test teardown to fail silently (the directory persists). The `code_project` fixture in `test_codebase_integration.py:69` correctly calls `store.close()` before `rmtree`.

**Fix:** Add `components["store"].close()` before `shutil.rmtree` in both session fixtures.

**File:** `tests/conftest.py:143-146, 161-165`

### R26-M2: `_build_rag_components` creates then immediately closes default QdrantClient (Major)

Lines 102-110: `VaultStore(root)` creates a QdrantClient at `{root}/.qdrant/` (the default path). When `qdrant_suffix` is non-empty, the code immediately closes this client (line 105) and creates a new one at the suffixed path. This means:

1. A `.qdrant/` directory is created as a side effect (line 138 in `__init__`)
1. The first client is opened and closed for no reason
1. The `store.db_path` is monkey-patched after construction

This works but is wasteful and leaves an empty `.qdrant/` directory behind. A cleaner approach would pass the suffixed path directly to `VaultStore.__init__` or add a path parameter.

**File:** `tests/conftest.py:101-110`

### R26-m1: `integration/conftest.py` shadows parent `rag_components` with different Qdrant suffix (Minor)

`integration/conftest.py:14-29` redefines `rag_components` using `QDRANT_SUFFIX_UNIT` ("-fast-unit"), while the parent conftest uses `QDRANT_SUFFIX_FAST` ("-fast"). Both are session-scoped, both index the same 13 docs. Due to pytest fixture resolution, integration tests use `-fast-unit` and non-integration tests use `-fast`. This is intentional isolation but:

- Neither conftest documents WHY separate suffixes are needed
- If both suites run in the same session, two GPU model instances are NOT created (the model is session-scoped via `_build_rag_components`), but two separate Qdrant stores are
- The shadowing means a developer can't easily understand which fixture a given test uses

**File:** `integration/conftest.py:14-29`

## Coverage Gaps

### R26-M3: No integration test for `store.delete_documents` (Major)

`VaultStore.delete_documents(ids)` (store.py:309) has zero tests anywhere in the test suite. The vault incremental indexer calls this method to remove deleted documents (indexer.py `incremental_index` line ~740). Without a test:

- There's no verification that Qdrant `points_selector` with `_stable_id` correctly deletes vault points
- If `_stable_id` produces a collision, documents could be silently un-deletable

**File:** Missing from `test_store_integration.py`

### R26-M4: No integration test for vault incremental index with actual file changes (Major)

`test_indexer_integration.py:31-45` only tests `incremental_index()` when nothing has changed (expects `added=0, removed=0`). There is no test that:

1. Adds a new vault document after full index, then runs incremental and asserts `added > 0`
1. Deletes a vault document, then runs incremental and asserts `removed > 0`
1. Modifies a vault document, then runs incremental and asserts `updated > 0`

By contrast, `test_codebase_integration.py:117-130` does test adding a new file for codebase incremental. The vault side has no equivalent.

**File:** Missing from `test_indexer_integration.py`

### R26-M5: `test_store_integration.py:43-57` tests hybrid_search without sparse vector (Major)

The `test_hybrid_search_returns_results` test calls:

```python
store.hybrid_search(query_vector=query_vec, query_text="...", limit=5)
```

without passing `sparse_vector`. This means the test only exercises the dense-only prefetch path (single prefetch with FusionQuery). The actual hybrid path (dense + sparse RRF fusion) is never directly tested at the store level. The end-to-end search tests (`test_search_integration.py`) go through `VaultSearcher.search()` which does pass sparse vectors, but the store's hybrid fusion logic itself is not isolated-tested with both vector types.

**File:** `test_store_integration.py:43-57`

### R26-m2: No integration test for `hybrid_search_codebase` directly (Minor)

`store.hybrid_search_codebase()` (store.py:568) is never called directly in any integration test. It is exercised indirectly via `VaultSearcher.search_codebase()` in `test_codebase_integration.py:137-167`, but there is no isolated store-level test equivalent to `test_hybrid_search_returns_results` for the codebase collection.

**File:** Missing from `test_store_integration.py`

### R26-m3: No test for codebase incremental with file modification (Minor)

`test_codebase_integration.py:108-130` tests incremental after no-change and after adding a new file, but does not test modifying an existing file (which should trigger `removed > 0` for old chunks and `added > 0` for new chunks). This is the most common real-world scenario.

**File:** Missing from `test_codebase_integration.py`

### R26-m4: No test for codebase incremental with file deletion (Minor)

No test removes a source file and verifies that `incremental_index()` correctly reports `removed > 0` and the old chunks are gone from the store.

**File:** Missing from `test_codebase_integration.py`

## Setup/Teardown Issues

### R26-M6: `_vault_snapshot_reset` runs `git checkout` but does not verify success (Major)

`tests/conftest.py:188-196`: The autouse session fixture runs `git checkout -- test-project/.vault/` with `check=False`. If the git command fails (e.g., git not in PATH, or test-project directory moved), the test-project vault silently remains modified. This can cause subsequent test runs to see stale data. Should use `check=True` or at minimum log a warning on failure.

**File:** `tests/conftest.py:192-196`

### R26-m5: `code_project` fixture uses `shutil.rmtree(qdrant_dir)` without error handling (Minor)

`test_codebase_integration.py:70-72`: After `store.close()`, the fixture calls `shutil.rmtree(qdrant_dir)`. On Windows, file locks from the Qdrant WAL may not be fully released immediately after `close()`. The `rmtree` call has no `ignore_errors=True`, which could cause `PermissionError` on Windows CI. By contrast, the conftest session fixtures have this same issue (see R26-M1) but at a larger scale.

**File:** `test_codebase_integration.py:70-72`

### R26-m6: `test_search_empty_store` creates store but does not clean up Qdrant directory (Minor)

`test_store_integration.py:59-79`: The test creates `VaultStore(tmp_path)` and calls `store.close()` in a `finally` block, but the `.qdrant/` directory inside `tmp_path` is left behind. While `tmp_path` is pytest-managed and eventually cleaned up, the Qdrant lock files may cause issues on Windows if other tests in the session try to access `tmp_path` before cleanup.

**File:** `test_store_integration.py:66-79`

## Test Quality Issues

### R26-m7: `test_api_integration.py:165-175` tests engine singleton but not engine replacement (Minor)

`test_engine_singleton` verifies `get_engine(root)` returns the same instance for the same root. But there is no test calling `get_engine(different_root)` to verify the old engine is properly replaced and closed. This is the bug identified in R22b-M3/R24-M1 and also flagged as missing in R25-M6.

**File:** `test_api_integration.py:164-175`

### R26-m8: `test_search_all` only tests with vault data, not combined vault+code (Minor)

`test_search_integration.py:92-109`: `TestSearchAll.test_search_all_returns_vault_results` verifies `search_all` works, but the session fixture only indexes vault documents (no codebase indexing). So the test never exercises the score-mixing path where both vault and codebase results are present. The comment says "search_all on a vault-only index should return vault results" -- this is a valid test case, but the complementary test (vault + code results merged) is missing.

**File:** `test_search_integration.py:92-109`

## Summary

| Severity | Count | IDs                   |
| -------- | ----- | --------------------- |
| Major    | 6     | R26-M1 through R26-M6 |
| Minor    | 8     | R26-m1 through R26-m8 |

**Key themes:**

1. **Missing delete coverage** (M3): `store.delete_documents` has zero tests -- this is the most significant gap.
1. **Incomplete incremental testing** (M4, m3, m4): Only no-change and add-file cases tested. No modify-file or delete-file scenarios for either vault or codebase.
1. **Fixture teardown** (M1, M6, m5, m6): Session fixtures skip `store.close()`, risking `PermissionError` on Windows. Git checkout runs unchecked.
1. **Hybrid search undertested** (M5, m2): Store-level hybrid search tested only with dense vector, not true dense+sparse fusion.
1. **Previously-identified gaps confirmed** (m7, m8): Engine leak test and search_all mixed-source test still missing (cross-ref R25-M6, R25-m8).
