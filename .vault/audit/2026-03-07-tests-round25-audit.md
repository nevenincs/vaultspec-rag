---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-06-30'
---

# Round 25 Audit -- Full Test Suite

Scope: all 14 test files in `src/vaultspec_rag/tests/` plus 2 conftest files and 1 constants file.

## Test Correctness

### R25-M1: `test_incremental_index_no_changes` has dual markers -- `@pytest.mark.quality` on integration-marked module (Major)

`test_indexer_integration.py:31-32`: The class `TestVaultIndexer` has method `test_incremental_index_no_changes` decorated with `@pytest.mark.quality`, but the module has `pytestmark = [pytest.mark.integration]`. This test has TWO markers: `integration` and `quality`. Running `-m integration` will execute it, but it uses `rag_components_full` which is the full 213-doc fixture, making it slow and unexpected in the integration suite. Similarly, several tests in `TestDocumentPreparation` and `TestIndexEdgeCases` have `@pytest.mark.quality` on individual methods while inheriting the module-level `integration` marker. CLAUDE.md says "every test must have exactly one marker."

**File:** `test_indexer_integration.py:31, 71-73, 97-99, 115-116, 126-127`

### R25-M2: `test_api_integration.py` tests have redundant `@pytest.mark.integration` plus module-level marker (Major)

The module has `pytestmark = [pytest.mark.integration]`, but most methods also have explicit `@pytest.mark.integration` decorators (lines 21, 42, 80, 99, 106, 118, 129, 144, 164). This is harmless but violates the "exactly one marker" rule. More problematically, `test_index_incremental` (line 56) and `test_index_full` (line 71) have `@pytest.mark.quality` IN ADDITION to the module-level `integration`, giving them dual markers.

**File:** `test_api_integration.py:21, 42, 56, 71, 80, 99, 106, 118, 129, 144, 164`

### R25-M3: `TestRerank` integration tests live in unit test file (Major)

`test_search_unit.py:239-351`: The `TestRerank` class has `pytestmark = [pytest.mark.integration]` and uses the `rag_components` fixture (GPU + Qdrant). It lives in `test_search_unit.py`, a unit test file. Integration tests should live in `tests/integration/` per CLAUDE.md. This causes confusion: running unit tests with `-m unit` correctly skips these, but the file name implies all tests are unit tests.

**File:** `test_search_unit.py:239-351`

### R25-M4: `test_parse_query_latency` has `@pytest.mark.unit` inside `performance`-marked module (Major)

`test_performance.py:93`: `test_parse_query_latency` is decorated with `@pytest.mark.unit` but the module has `pytestmark = [pytest.mark.performance]`. This gives it dual markers. When running `-m unit`, this test will execute but the rest of the performance file won't -- unexpected behavior.

**File:** `test_performance.py:93`

### R25-m1: Redundant `@pytest.mark.unit` decorators on individual tests in unit-marked modules (Minor)

Several classes in `test_indexer_unit.py` have explicit `@pytest.mark.unit` on individual methods despite the module already having `pytestmark = [pytest.mark.unit]`:

- `test_metadata_excludes_unhashed_files` (line 507)
- `TestR10MinorNodeTypes` methods (lines 967-985)
- `TestR10MinorContainerConstant.test_container_nodes_exists` (line 991)
- `TestR10MinorAnchoredPattern.test_anchored_pattern_no_double_slash` (line 1001)
- `TestR10MinorBufferFunctionName.test_buffer_inherits_function_name` (line 1033)
- `TestR11M1NonAsciiChunkText` methods (lines 1057, 1071)

Also `test_store_codebase.py:55` (`test_build_code_filter`) has no marker but its module-level `pytestmark = [pytest.mark.integration]` covers it.

**File:** `test_indexer_unit.py:507, 967-985, 991, 1001, 1033, 1057, 1071`

## Structural Issues

### R25-M5: `inspect.getsource()` tests are fragile structural assertions (Major)

`test_indexer_unit.py:857-880`: Two tests use `inspect.getsource()` to grep the implementation source code:

- `test_write_meta_uses_current_hashes_not_current_files` (line 857-865) asserts `"self._write_meta(current_hashes)" in source`
- `test_unhashed_files_removed_from_current_files` (line 872-880) asserts `"set(current_files) - set(current_hashes)" in source`

These are not behavioral tests -- they verify exact source code strings. Any refactoring (variable rename, extraction into helper, etc.) breaks them even if behavior is preserved. These should be replaced with behavioral integration tests that exercise the actual incremental indexing logic.

**File:** `test_indexer_unit.py:857-865, 872-880`

### R25-m2: `integration/conftest.py` redefines session-scoped `rag_components` fixture (Minor)

`integration/conftest.py:14-29` defines a `rag_components` fixture that shadows the parent `tests/conftest.py:131-147` fixture. Both are session-scoped, both call `_build_rag_components` with `fast=True`, but they use different `qdrant_suffix` values (`QDRANT_SUFFIX_UNIT` vs `QDRANT_SUFFIX_FAST`). This means integration tests and unit tests that use `rag_components` get different Qdrant instances with different suffixes. This is intentional isolation, but the shadowing is implicit and undocumented -- a developer looking at integration tests won't realize they use a different fixture than the unit tests.

**File:** `integration/conftest.py:14-29`

### R25-m3: `TestChunkIDFormat` tests are tautological (Minor)

`test_indexer_unit.py:250-262`: Both tests in `TestChunkIDFormat` construct the expected value themselves and assert against it:

- `test_id_contains_hash` builds `chunk_id` from `expected_hash` then asserts `expected_hash in chunk_id`
- `test_different_content_different_hash` computes two hashes and asserts they differ

Neither test calls any production code -- they test Python's `hashlib.sha256` in isolation. They should call `CodebaseIndexer._chunk_with_ast` or `_chunk_file` and verify the actual chunk IDs produced.

**File:** `test_indexer_unit.py:250-262`

### R25-m4: `TestChunkIDUniqueness.test_identical_blocks_different_ids` is tautological (Minor)

`test_indexer_unit.py:403-412`: The test manually constructs two ID strings (`id_a = f"dup.py:1-2:{chunk_hash}"`, `id_b = f"dup.py:5-6:{chunk_hash}"`) and asserts they differ. This tests string formatting, not production code. The companion test `test_identical_blocks_chunked_separately` (line 414) is a proper behavioral test.

**File:** `test_indexer_unit.py:403-412`

## Missing Test Coverage

### R25-M6: No tests for `api.py` `get_engine` resource leak on root_dir change (Major)

R22b-M3/R24-M1 identified that `get_engine` leaks the old `QdrantClient` when `root_dir` changes. `test_api_integration.py:164-175` tests `test_engine_singleton` for same root, but there is no test verifying that calling `get_engine` with a different root properly closes the old engine. This is a known bug with no regression test.

**File:** Missing from `test_api_integration.py`

### R25-m5: No tests for `embeddings.py` OOM retry logic (Minor)

R22b-m10 noted that `encode_documents` and `encode_documents_sparse` have OOM retry loops, but no test exercises this path. The retry logic halves the batch size on `OutOfMemoryError` -- a behavioral test could verify this by encoding a batch large enough to trigger the retry on constrained GPU memory.

**File:** Missing from `integration/test_embeddings.py`

### R25-m6: No tests for `store.py` date filter semantics (Minor)

R22b-M1 found that `_build_filter` uses `MatchText` for date, which tokenizes on hyphens instead of doing prefix matching. No test verifies whether `date:2026-02` actually matches documents from February 2026 vs any document containing token "02". `test_quality.py:173-192` tests the end-to-end date filter but uses `date:2026-02-06` (exact date), not a month prefix like `date:2026-02`.

**File:** Missing from `test_store.py` or `test_quality.py`

### R25-m7: No tests for `config.py` `__getattr__` performance (Minor)

R24-M5 found that `VaultSpecConfigWrapper.__getattr__` recreates the `rag_defaults` dict on every attribute access. No test measures this overhead or verifies the behavior.

**File:** Missing

### R25-m8: No tests for `search.py` `search_all` mixed-score ranking (Minor)

R21-M1 identified that `search_all` mixes incomparable scores from vault and codebase results. No test verifies the ranking behavior of `search_all` when both sources return results. `test_search_integration.py:92-109` only tests `search_all` with vault-only data.

**File:** `test_search_integration.py:92-109`

## Banned Pattern Compliance

### R25-PASS: No banned patterns found

All 14 test files were checked for:

- `unittest.mock`, `MagicMock`, `patch()`, `monkeypatch` -- **NONE FOUND**
- `import unittest` -- **NONE FOUND**
- `pytest.skip()`, `@pytest.mark.skip`, `skipIf`, `skipUnless` -- **NONE FOUND**
- Synthetic/fake embeddings (e.g., `[0.1]*1024`) -- **NONE FOUND** (test_store_codebase.py correctly uses real model output)

## Summary

| Severity | Count | IDs                   |
| -------- | ----- | --------------------- |
| Major    | 6     | R25-M1 through R25-M6 |
| Minor    | 8     | R25-m1 through R25-m8 |

**Key themes:**

1. **Marker discipline** (M1, M2, M3, M4, m1): Multiple tests have dual markers violating the "exactly one marker" rule. Integration tests in wrong directory.
1. **Fragile/tautological tests** (M5, m3, m4): Tests that verify source code strings or test hashlib instead of production behavior.
1. **Missing coverage** (M6, m5-m8): Known bugs from prior audits have no regression tests.
1. **Banned patterns**: Clean -- no mocks, skips, or synthetic data remain.
