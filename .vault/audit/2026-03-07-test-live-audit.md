---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# Comprehensive Test Suite Audit

**Date:** 2026-03-07
**Auditor:** docs-researcher-2-2
**Scope:** All 24 test files in `src/vaultspec_rag/tests/`

## Files Audited

| #   | File                                       | Lines | Tests | Marker             |
| --- | ------------------------------------------ | ----- | ----- | ------------------ |
| 1   | `test_indexer_unit.py`                     | 1078  | ~55   | `unit`             |
| 2   | `test_search_unit.py`                      | 239   | ~20   | `unit` (per-class) |
| 3   | `test_store.py`                            | 146   | ~12   | `unit`             |
| 4   | `test_adr_regression.py`                   | 291   | ~20   | `unit`             |
| 5   | `test_mcp_server.py`                       | 300   | ~22   | `unit`             |
| 6   | `test_cli.py`                              | 128   | ~17   | `unit`             |
| 7   | `test_store_codebase.py`                   | 91    | ~5    | `integration`      |
| 8   | `integration/test_indexer_integration.py`  | 203   | ~9    | `integration`      |
| 9   | `integration/test_search_integration.py`   | 375   | ~14   | `integration`      |
| 10  | `integration/test_store_integration.py`    | 143   | ~7    | `integration`      |
| 11  | `integration/test_embeddings.py`           | 78    | ~7    | `integration`      |
| 12  | `integration/test_codebase_integration.py` | 264   | ~11   | `integration`      |
| 13  | `integration/test_api_integration.py`      | 165   | ~11   | `integration`      |
| 14  | `integration/test_cli_integration.py`      | 106   | ~6    | `integration`      |
| 15  | `integration/test_quality.py`              | 371   | ~13   | `quality`          |
| 16  | `integration/test_robustness.py`           | 85    | ~3    | `robustness`       |
| 17  | `integration/test_performance.py`          | 225   | ~10   | `performance`      |
| 18  | `benchmarks/bench_rag.py`                  | 246   | ~5    | `performance`      |
| 19  | `conftest.py`                              | 253   | —     | fixtures           |
| 20  | `integration/conftest.py`                  | 31    | —     | fixtures           |
| 21  | `benchmarks/conftest.py`                   | 57    | —     | fixtures           |
| 22  | `constants.py`                             | 78    | —     | constants          |
| 23  | `__init__.py`                              | —     | —     | —                  |
| 24  | `integration/__init__.py`                  | —     | —     | —                  |

______________________________________________________________________

## 1. Tautological Tests

### MEDIUM: `test_store.py:130-145` — `TestPackageExports` tests only assert `is not None` or `callable()`

```
test_codechunk_importable:     assert CodeChunk is not None
test_codebase_indexer_importable: assert CodebaseIndexer is not None
test_api_facade_functions_importable: assert callable(index_codebase) ...
```

**File:** `test_store.py:130-145`
**Violation:** These tests pass as long as the import succeeds. Asserting `is not None` on a class is tautological — if the import fails, pytest already errors before reaching the assertion. The `callable()` checks are marginally better but still test the language, not the application.
**Recommendation:** Delete or replace with tests that exercise the actual exports (e.g., verify function signatures, verify they are the correct types from the correct modules).

### LOW: `test_indexer_unit.py:246-247` — `TestFileSizeLimit.test_max_file_size_is_10mb`

```python
def test_max_file_size_is_10mb(self):
    assert _MAX_FILE_SIZE == 10 * 1024 * 1024
```

**File:** `test_indexer_unit.py:246-247`
**Violation:** Tests a constant's value. If someone changes `_MAX_FILE_SIZE`, the test fails — but it doesn't verify the constant is *used* correctly. This is borderline (documenting an API contract) but technically tautological.

### LOW: `test_adr_regression.py:181-185` — `TestGraphCache.test_graph_cache_has_lock`

```python
def test_graph_cache_has_lock(self):
    cache = _GraphCache()
    assert hasattr(cache, "_lock")
```

**File:** `test_adr_regression.py:181-185`
**Violation:** Asserts a private attribute exists. Does not verify it is actually a `Lock`, or that it is used. Barely meaningful.

### LOW: `test_adr_regression.py:278-283` — `TestRagComponentsDataclass.test_is_dataclass`

```python
def test_is_dataclass(self):
    assert dataclasses.is_dataclass(RagComponents)
```

**File:** `test_mcp_server.py:278-283`
**Violation:** Tests Python's `@dataclass` decorator, not application behavior.

______________________________________________________________________

## 2. Mocks / Patches / Stubs / Fakes

### CLEAR: No violations found

No files contain `unittest.mock`, `MagicMock`, `@patch`, `monkeypatch`, `mocker`, `responses`, `httpretty`, or fake objects. All tests use real infrastructure.

**Exception noted:** `test_mcp_server.py:246-264` — `TestGetCompFailureCaching.test_comp_error_cached` directly manipulates module-level globals (`mod._comp`, `mod._comp_error`) to simulate a prior failure. This is NOT a mock/patch — it modifies real module state and restores it in a `try/finally`. This is acceptable for testing the failure caching path without triggering actual GPU initialization.

______________________________________________________________________

## 3. Skips

### CLEAR: No violations found

No files contain `pytest.skip`, `@pytest.mark.skip`, `skipif`, `skipUnless`, or any skip mechanism.

______________________________________________________________________

## 4. Marker Violations

### MEDIUM: `benchmarks/bench_rag.py:35-152` — Tests use `@pytest.mark.performance` but also accept parameters and return dicts

**File:** `benchmarks/bench_rag.py:36,56,71,85,133`
**Tests:** `test_bench_embedding_throughput`, `test_bench_full_index`, `test_bench_incremental_noop`, `test_bench_search_latency`, `test_bench_memory`
**Violation:** These test functions accept non-fixture parameters like `n_docs: int = 50` (line 36) and return `dict` results. When run via `pytest`, extra parameters cause `TypeError` unless there's a matching fixture. The `main()` function (line 155) calls them directly with positional args, bypassing pytest. When run via `pytest -m performance`, `test_bench_embedding_throughput(model, n_docs=50)` works because `n_docs` has a default, but `test_bench_full_index(root, model, store, indexer)` requires 4 fixtures — `root`, `model`, `store`, `indexer` — which are defined in `benchmarks/conftest.py`. The return values are silently discarded by pytest.

**Assessment:** The tests work when run via pytest (fixtures provide the args, defaults handle extra params), but the dual-use design (pytest + standalone `main()`) is fragile. The `return dict` pattern is unusual — these should use `print()` or `capsys` under pytest, or just be benchmarks without assertions.

### LOW: `test_search_unit.py:9-13` — Per-class `pytestmark` instead of module-level

**File:** `test_search_unit.py:9,13,21,42,75,167`
**Comment:** Line 9 says `# No module-level pytestmark — each class sets its own marker`. All 5 classes use `pytestmark: ClassVar = [pytest.mark.unit]`. This works but is inconsistent with every other test file which uses module-level `pytestmark`. Should be normalized to module-level.

______________________________________________________________________

## 5. Missing Integration Coverage

### HIGH: No test for `vaultspec-rag index --type code` CLI command

**File:** `integration/test_cli_integration.py`
**Gap:** `TestCLIIndex` only tests `--type vault`. The `--type code` path (codebase indexing via CLI) has no end-to-end test. This is a significant gap because the CLI's `handle_index` function has separate branches for vault vs. code indexing.

### HIGH: No test for `vaultspec-rag search --type code` CLI command

**File:** `integration/test_cli_integration.py`
**Gap:** `TestCLISearch` only tests default search (vault). The `--type code` flag and `search_codebase` CLI path are untested end-to-end.

### MEDIUM: No test for `vaultspec-rag index --clean` CLI flag

**File:** `integration/test_cli_integration.py`
**Gap:** The `--clean` flag triggers store deletion and recreation (cli.py lines 181-194). This critical path is untested via CLI. It is tested indirectly through `test_double_full_index_idempotent` in `test_indexer_integration.py`, but the CLI's cleanup logic (close store, delete directory, recreate) has no coverage.

### MEDIUM: No integration test for `search_all()` with both vault AND code results

**File:** `integration/test_search_integration.py:138-155`
**Gap:** `TestSearchAll.test_search_all_returns_vault_results` only indexes vault docs (via `rag_components` fixture). It never indexes codebase chunks, so `search_all()` never returns mixed vault+code results. The test comment even says "search_all on a vault-only index". There's no test that exercises the min-max normalization across both result sets.

### MEDIUM: No test for `VaultStore.hybrid_search_codebase()` with filters

**File:** `integration/test_store_integration.py`
**Gap:** `test_hybrid_search_with_sparse_vector` tests vault hybrid search. There's no matching test for `hybrid_search_codebase()` with language/path filters applied. `test_codebase_integration.py` tests via `VaultSearcher.search_codebase()` which does exercise `hybrid_search_codebase`, but never with explicit filter verification beyond language.

### LOW: No test for `TextSplitter` fallback with `max_embed_chars` truncation

**File:** `test_indexer_unit.py`
**Gap:** The `TextSplitter` is tested via `_chunk_with_splitter` but never with a chunk exceeding `max_embed_chars`. Truncation at embedding time (`embeddings.py:230-232`) is untested.

### LOW: No test for `VaultIndexer.incremental_index` mtime comparison

**File:** `integration/test_indexer_integration.py`
**Gap:** The vault incremental indexer uses `st_mtime` float comparison (R23-M2). Tests verify the end result (added/removed counts) but don't test the edge case of sub-second modifications that might have identical mtimes.

______________________________________________________________________

## 6. Missing CLI Coverage

### Covered (integration/test_cli_integration.py)

- `vaultspec-rag status` — 2 tests (GPU info, document counts)
- `vaultspec-rag index --type vault` — 2 tests (summary, counts)
- `vaultspec-rag search "query"` — 2 tests (returns results, gibberish no crash)

### Covered (test_cli.py unit tests)

- `--help` — 3 tests (usage, commands, no-args)
- `--version` — 1 test
- `test` subcommand — 3 tests (help, marker flags, multiple args)
- `server` subcommand — 6 tests (mcp help/stop/status, service start/stop/status)
- Workspace required — 3 tests (index/search/status with nonexistent path)

### NOT Covered

- `vaultspec-rag index --type code` — **no test** (HIGH)
- `vaultspec-rag index --clean` — **no test** (MEDIUM)
- `vaultspec-rag search --type code "query"` — **no test** (HIGH)
- `vaultspec-rag search` with `--top-k` flag — **no test** (LOW)
- `vaultspec-rag index --type all` — **no test** (LOW)
- `vaultspec-rag server mcp start` (blocked — would start a real server) — acceptable gap

______________________________________________________________________

## 7. Other Issues

### MEDIUM: `benchmarks/bench_rag.py:234-237` — `main()` cleanup doesn't call `store.close()` before `shutil.rmtree()`

**File:** `benchmarks/bench_rag.py:234-237`

```python
qdrant_dir = TEST_PROJECT / ".qdrant"
if qdrant_dir.exists():
    shutil.rmtree(qdrant_dir)
```

**Issue:** The `store` variable (line 187) holds an open `QdrantClient` with file locks. `shutil.rmtree()` without closing the store first will raise `PermissionError` on Windows. The `benchmarks/conftest.py` correctly calls `store.close()` before cleanup.

### LOW: `conftest.py:170-176` — `require_gpu_corpus` fixture is vestigial

**File:** `conftest.py:170-176`

```python
@pytest.fixture
def require_gpu_corpus(rag_components):
    """Kept for backward compatibility with test files that reference it."""
    assert rag_components["model"] is not None
```

**Issue:** Only used in `test_quality.py` via `@pytest.mark.usefixtures("require_gpu_corpus")`. The assertion (`model is not None`) is tautological — if model loading failed, the `rag_components` fixture would have already errored. This fixture adds no value beyond forcing `rag_components` to be available, which `rag_components` parameter already does.

### LOW: `integration/conftest.py` duplicates `rag_components` fixture from parent

**File:** `integration/conftest.py:14-30`
**Issue:** This defines a `rag_components` fixture with `QDRANT_SUFFIX_UNIT`, but the parent `conftest.py:131-147` defines `rag_components` with `QDRANT_SUFFIX_FAST`. Both are session-scoped. Tests in `integration/` get the unit conftest's version. The naming collision is confusing — both are "fast" 13-doc indexes but with different qdrant suffixes.

______________________________________________________________________

## Summary

| Category                     | HIGH  | MEDIUM | LOW    | CLEAR       |
| ---------------------------- | ----- | ------ | ------ | ----------- |
| Tautological tests           | 0     | 1      | 3      | —           |
| Mocks/patches/stubs          | —     | —      | —      | CLEAR       |
| Skips                        | —     | —      | —      | CLEAR       |
| Marker violations            | 0     | 1      | 1      | —           |
| Missing integration coverage | 2     | 3      | 2      | —           |
| Missing CLI coverage         | 2     | 1      | 2      | —           |
| Other issues                 | 0     | 2      | 2      | —           |
| **TOTAL**                    | **4** | **8**  | **10** | **2 CLEAR** |

### Priority actions

1. **HIGH:** Add CLI integration tests for `--type code` (index and search)
1. **HIGH:** Add integration test for `search_all()` with mixed vault+code results
1. **MEDIUM:** Add CLI test for `--clean` flag
1. **MEDIUM:** Fix `bench_rag.py` `main()` to call `store.close()` before cleanup
1. **MEDIUM:** Delete or replace tautological `TestPackageExports` tests
1. **MEDIUM:** Fix benchmark dual-use design (return values, non-fixture params)
