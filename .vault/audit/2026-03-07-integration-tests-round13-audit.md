---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-06-30'
---

# Round 13 Audit -- Integration Tests and Benchmarks

**Auditor:** docs-researcher-2-2
**Files:**

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` (197 lines)
- `src/vaultspec_rag/tests/benchmarks/bench_rag.py` (251 lines)
- `src/vaultspec_rag/tests/integration/conftest.py` (31 lines)
- `src/vaultspec_rag/tests/conftest.py` (245 lines) -- shared fixtures
- `src/vaultspec_rag/tests/constants.py` (78 lines) -- test constants
  **Date:** 2026-03-07

______________________________________________________________________

## Check 1: Test Correctness -- Full Pipeline Exercise

### `test_indexer_integration.py`

Tests exercise real pipeline stages:

| Test                                     | Pipeline Stage                   | Meaningful?                                          |
| ---------------------------------------- | -------------------------------- | ---------------------------------------------------- |
| `test_full_index_counts`                 | index -> verify counts           | Yes -- checks total > 0, added > 0, device == "cuda" |
| `test_index_matches_store_count`         | index -> store.count()           | Yes -- verifies result.total == store.count()        |
| `test_incremental_index_no_changes`      | full_index -> incremental_index  | Yes -- verifies 0 added/removed after no changes     |
| `test_prepare_real_document`             | scan_vault -> prepare_document   | Yes -- checks id, path, doc_type enum, content       |
| `test_prepare_all_documents`             | scan all -> prepare all          | Partial -- see R13-M1                                |
| `test_double_full_index_idempotent`      | full_index x2 -> count match     | Yes -- idempotency check                             |
| `test_incremental_after_full_stable`     | full -> incremental -> 0 changes | Yes                                                  |
| `test_docs_without_frontmatter_counted`  | scan -> parse metadata           | Yes -- validates corpus characteristics              |
| `test_incremental_detects_modified_file` | modify file -> incremental       | Yes -- mutates file, checks updated >= 1, restores   |
| `test_incremental_detects_deleted_file`  | delete file -> incremental       | Yes -- deletes file, checks removed >= 1, restores   |

**Verdict: PASS overall.** Tests exercise real indexing with real GPU models on real vault data. Modify/delete tests use try/finally for cleanup.

______________________________________________________________________

## Check 2: Fixture Teardown -- `store.close()` Before `rmtree`

### `integration/conftest.py` (lines 25-30)

```python
yield components
components["store"].close()
db_dir = components["db_dir"]
if db_dir.exists():
    shutil.rmtree(db_dir)
```

### `tests/conftest.py` -- `rag_components` (lines 142-147) and `rag_components_full` (lines 162-167)

Same pattern: `store.close()` then `shutil.rmtree(db_dir)`.

**Verdict: PASS.** All three fixture teardowns call `store.close()` before `shutil.rmtree()`. This releases Qdrant's file locks before deleting the directory (critical on Windows).

______________________________________________________________________

## Check 3: Git Reset Safety

### `_vault_snapshot_reset` fixture (conftest.py lines 190-198)

```python
@pytest.fixture(scope="session", autouse=True)
def _vault_snapshot_reset():
    yield
    subprocess.run(
        ["git", "checkout", "--", "test-project/.vault/"],
        cwd=PROJECT_ROOT,
        check=True,
    )
```

### R13-M1: `_vault_snapshot_reset` uses `check=True` -- test session fails on git error (MEDIUM)

If `git checkout` fails (e.g., detached HEAD, missing `.vault/`, git not in PATH), the entire test session teardown raises `subprocess.CalledProcessError`. This masks the actual test results. Should use `check=False` and log a warning instead, since this is cleanup code.

**File:** `conftest.py:194-198`

______________________________________________________________________

## Check 4: Real Data Assertions

### `test_prepare_all_documents` (lines 71-86)

```python
for path in scan_vault(TEST_PROJECT):
    doc = prepare_document(path, TEST_PROJECT)
    if doc is not None:
        prepared += 1
        assert doc.id == path.stem    # <--- WRONG
    else:
        skipped += 1
assert prepared > 0
```

### R13-M2: `test_prepare_all_documents` asserts `doc.id == path.stem` -- incorrect after path-based ID fix (HIGH)

`prepare_document()` now uses `rel_path.rsplit(".", 1)[0]` as the document ID (indexer.py:593), which produces relative-path IDs like `"adr/overview"` for nested documents. But this test asserts `doc.id == path.stem`, which only checks the filename stem (e.g., `"overview"`).

For documents directly in the docs root, `doc.id == path.stem` happens to be true. But for documents in subdirectories (e.g., `docs/adr/overview.md`), `doc.id` is `"adr/overview"` while `path.stem` is `"overview"` -- the assertion would fail.

If this test currently passes, it means all test-project documents are in the docs root (no subdirectories), or the test is not being run. Either way, the assertion is wrong and will break when subdirectory documents are added to the test corpus.

**File:** `test_indexer_integration.py:82`

### Other assertions

Most other tests use meaningful assertions:

- `result.total > 0` (line 20) -- not just `len(results) > 0`, checks a specific field
- `result.device == "cuda"` (line 23) -- verifies GPU execution
- `result.total == store.count()` (line 29) -- cross-validates indexer vs store
- `result.added == 0` / `result.removed == 0` (lines 41-42) -- verifies stability
- `doc.doc_type in ("adr", "audit", "exec", "plan", "reference", "research")` (line 67) -- validates enum membership
- `result.updated >= 1` (line 165) -- validates modification detection
- `store.count() < count_before` (line 191) -- validates deletion

**Verdict: Mostly PASS.** Assertions are meaningful except for the `doc.id == path.stem` issue.

______________________________________________________________________

## Check 5: Marker Compliance

### `test_indexer_integration.py`

Line 9: `pytestmark = [pytest.mark.integration]` -- applies to ALL tests in the file.

No individual `@pytest.mark.unit` or other conflicting markers.

**Verdict: PASS.** Module-level `pytestmark` correctly marks all tests as `integration`.

### `bench_rag.py`

```python
@pytest.mark.benchmark
@pytest.mark.quality
def test_bench_embedding_throughput(...)
```

All 5 benchmark functions have `@pytest.mark.benchmark` and `@pytest.mark.quality`.

### R13-M3: Benchmark tests use `@pytest.mark.benchmark` which is not in the approved marker set (MEDIUM)

CLAUDE.md defines approved markers: `unit`, `integration`, `quality`, `performance`, `robustness`. The marker `benchmark` is not in this list. The benchmarks should use `@pytest.mark.performance` instead of (or in addition to) `@pytest.mark.benchmark`.

Note: Each benchmark already has `@pytest.mark.quality` which IS approved. But `@pytest.mark.benchmark` is unregistered and will produce a pytest warning with `--strict-markers`.

**File:** `bench_rag.py:35-36, 56-57, 72-73, 87-88, 136-137`

______________________________________________________________________

## Check 6: Timeout Markers

### `test_indexer_integration.py`

| Test                                     | Timeout                     |
| ---------------------------------------- | --------------------------- |
| `test_full_index_counts`                 | `@pytest.mark.timeout(60)`  |
| `test_index_matches_store_count`         | `@pytest.mark.timeout(60)`  |
| `test_incremental_index_no_changes`      | `@pytest.mark.timeout(300)` |
| `test_prepare_real_document`             | `@pytest.mark.timeout(60)`  |
| `test_prepare_all_documents`             | `@pytest.mark.timeout(300)` |
| `test_double_full_index_idempotent`      | `@pytest.mark.timeout(300)` |
| `test_incremental_after_full_stable`     | `@pytest.mark.timeout(300)` |
| `test_docs_without_frontmatter_counted`  | `@pytest.mark.timeout(300)` |
| `test_incremental_detects_modified_file` | `@pytest.mark.timeout(300)` |
| `test_incremental_detects_deleted_file`  | `@pytest.mark.timeout(300)` |

**Verdict: PASS.** All 10 tests have explicit timeout markers. Fast tests get 60s, full-corpus tests get 300s.

### `bench_rag.py`

No timeout markers on any benchmark. Since benchmarks are long-running by nature, this is acceptable -- they have `@pytest.mark.quality` which implies longer runtimes.

______________________________________________________________________

## Check 7: Benchmark Structure

### `bench_rag.py`

5 benchmark test functions:

1. `test_bench_embedding_throughput` -- times `encode_documents()` on synthetic texts
1. `test_bench_full_index` -- times `full_index()` on real corpus
1. `test_bench_incremental_noop` -- times `incremental_index()` with no changes
1. `test_bench_search_latency` -- measures p50/p95/p99 over 20 real queries
1. `test_bench_memory` -- reports GPU VRAM and Qdrant disk size

### R13-m1: Benchmark test functions take non-fixture parameters (Minor)

`test_bench_embedding_throughput(model, n_docs: int = 50)` and `test_bench_search_latency(searcher, n_queries: int = 20)` have non-fixture parameters (`n_docs`, `n_queries`) with defaults. Pytest will not inject these -- they will use the default values. But `model`, `store`, `indexer`, `searcher`, `root` are also not defined as fixtures in any conftest. These functions work when called from `main()` directly (passing arguments), but will fail when run via `pytest` because the fixtures don't exist.

**File:** `bench_rag.py:37, 89`

### R13-M4: Benchmark tests reference undefined fixtures (`model`, `store`, `indexer`, `searcher`, `root`) (MEDIUM)

The benchmark test functions accept parameters like `model`, `store`, `indexer`, `searcher`, `root` that are not defined as pytest fixtures anywhere in the fixture chain:

- `integration/conftest.py` only defines `rag_components` (a dict)
- `tests/conftest.py` defines `rag_components` and `rag_components_full` (both dicts)
- No fixture named `model`, `store`, `indexer`, `searcher`, or `root` exists

These benchmarks can only work when called from the `main()` function (lines 160-250), not via `pytest`. Running `pytest bench_rag.py` will fail with fixture lookup errors.

**File:** `bench_rag.py:37, 58, 74, 89, 138`

______________________________________________________________________

## Check 8: Banned Imports (unittest, mocks, skips)

### `test_indexer_integration.py`

Imports: `pytest`, `..constants.TEST_PROJECT`. No `unittest`, no `mock`, no `skip`.

### `bench_rag.py`

Imports: `shutil`, `statistics`, `sys`, `time`, `pytest`, `..constants.TEST_PROJECT`. No `unittest`, no `mock`, no `skip`.

### `integration/conftest.py`

Imports: `shutil`, `pytest`, `..conftest._build_rag_components`, `..constants.*`. No `unittest`, no `mock`, no `skip`.

### `tests/conftest.py`

Imports: `shutil`, `subprocess`, `time`, `pytest`, `vaultspec.config`, `vaultspec_rag.config`, `.constants.*`. No `unittest`, no `mock`, no `skip`.

**Verdict: PASS.** Zero violations across all 5 files.

______________________________________________________________________

## Check 9: Conftest Fixture Scoping

| Fixture                        | Scope                     | File                    | Assessment                                                       |
| ------------------------------ | ------------------------- | ----------------------- | ---------------------------------------------------------------- |
| `rag_components` (integration) | `session`                 | integration/conftest.py | **Correct** -- GPU model load is expensive, share across session |
| `rag_components` (shared)      | `session`                 | tests/conftest.py       | **Correct** -- same reasoning                                    |
| `rag_components_full`          | `session`                 | tests/conftest.py       | **Correct** -- full corpus index is very expensive               |
| `require_gpu_corpus`           | `function` (default)      | tests/conftest.py       | **Correct** -- just an assertion wrapper                         |
| `_vault_snapshot_reset`        | `session`, `autouse=True` | tests/conftest.py       | **Correct** -- reset once after all tests                        |
| `vaultspec_config`             | `function` (default)      | tests/conftest.py       | **Correct** -- resets singleton per test                         |
| `config_override`              | `function` (default)      | tests/conftest.py       | **Correct** -- factory fixture, resets per test                  |
| `clean_config`                 | `function` (default)      | tests/conftest.py       | **Correct** -- resets singleton per test                         |

### R13-m2: Two `rag_components` fixtures with `session` scope in different conftest files (Minor)

`integration/conftest.py` defines `rag_components(session)` using `QDRANT_SUFFIX_UNIT`, and `tests/conftest.py` defines `rag_components(session)` using `QDRANT_SUFFIX_FAST`. pytest's fixture resolution means the integration tests will use the closer (integration/conftest.py) fixture, while unit tests use the shared one. This works correctly but could cause confusion -- two fixtures with the same name, same scope, different qdrant directories.

**File:** `integration/conftest.py:14-30`, `tests/conftest.py:131-147`

**Verdict: PASS overall.** Scoping is correct across all fixtures.

______________________________________________________________________

## Check 10: Hardcoded Paths

### `constants.py`

```python
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
TEST_PROJECT = PROJECT_ROOT / "test-project"
```

All paths are derived from `__file__` -- no hardcoded absolute paths.

### `bench_rag.py`

```python
_repo = _Path(__file__).resolve().parent.parent.parent.parent.parent
```

Also derived from `__file__`.

### `conftest.py`

```python
subprocess.run(
    ["git", "checkout", "--", "test-project/.vault/"],
    cwd=PROJECT_ROOT,
    ...
)
```

Uses `PROJECT_ROOT` (derived from `__file__`) as cwd. The `"test-project/.vault/"` path is relative to the git root.

**Verdict: PASS.** No hardcoded absolute paths. All paths are relative to `__file__` or `PROJECT_ROOT`.

______________________________________________________________________

## Additional Observations

### `bench_rag.py` main() cleanup does not call `store.close()` (line 240-242)

```python
qdrant_dir = TEST_PROJECT / ".qdrant"
if qdrant_dir.exists():
    shutil.rmtree(qdrant_dir)
```

The `store` created at line 192 is never closed before `shutil.rmtree()`. On Windows, this will fail with `PermissionError` because Qdrant holds file locks.

### R13-m3: `bench_rag.py` main() does not close store before rmtree (Minor)

**File:** `bench_rag.py:240-242` (should call `store.close()` at line 239)

______________________________________________________________________

## Summary

| ID     | Severity | Finding                                                                                          |
| ------ | -------- | ------------------------------------------------------------------------------------------------ |
| R13-M1 | MEDIUM   | `_vault_snapshot_reset` uses `check=True` on git checkout -- teardown failure masks test results |
| R13-M2 | HIGH     | `test_prepare_all_documents` asserts `doc.id == path.stem` -- wrong after path-based ID change   |
| R13-M3 | MEDIUM   | Benchmarks use `@pytest.mark.benchmark` (unregistered) instead of `@pytest.mark.performance`     |
| R13-M4 | MEDIUM   | Benchmark test functions reference undefined fixtures -- cannot run via pytest                   |
| R13-m1 | MINOR    | Benchmark functions have non-fixture parameters with defaults (only work from `main()`)          |
| R13-m2 | MINOR    | Two `rag_components` fixtures with same name in different conftest files                         |
| R13-m3 | MINOR    | `bench_rag.py` main() does not close store before rmtree (Windows PermissionError)               |

**1 HIGH, 3 MEDIUM, 3 MINOR findings.**
