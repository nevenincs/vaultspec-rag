---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-07
related: []
---
# Test Mandate Compliance Audit — 2026-03-07

## Scope

Exhaustive review of all test files against CLAUDE.md testing mandates:

1. No mocks, patches, fakes, stubs, monkeypatches
2. No unittest imports
3. No pytest.skip / @pytest.mark.skip
4. No tautological tests
5. No synthetic embeddings
6. Every test must have exactly one marker

## Banned Pattern Scan

Grep for: `unittest`, `MagicMock`, `@patch`, `monkeypatch`, `pytest.skip`, `Mock(`, `responses`, `httpretty`, `pytest.mark.skip`, `[0.1]*`, `np.zeros`, `np.ones`, `torch.rand`, `fake`, `synthetic`, `dummy`

**Result: ZERO matches across all 22 test files.** All previously-reported mock/skip violations (Tasks #54, #55, #60, #61) have been fixed.

---

## Violations Found

### V1: TAUTOLOGICAL — `inspect.getsource` structural assertions

**File:** `src/vaultspec_rag/tests/test_indexer_unit.py`

These tests assert that specific string patterns exist in production source code via `inspect.getsource()`. They test the text of the code, not its behavior. If the implementation is refactored to use equivalent logic with different variable names, these tests break. If the implementation is wrong but uses the expected string, these tests pass.

#### V1a: `test_write_meta_uses_current_hashes_not_current_files` (line 841-849)

```python
def test_write_meta_uses_current_hashes_not_current_files(self):
    import inspect
    from vaultspec_rag.indexer import CodebaseIndexer
    source = inspect.getsource(CodebaseIndexer.incremental_index)
    assert "self._write_meta(current_hashes)" in source
```

**Violation:** Tautological. Tests string content of source code, not behavior.
**Verdict:** DELETE — replace with behavioral integration test that verifies metadata is correct after incremental index.

#### V1b: `test_unhashed_files_removed_from_current_files` (line 856-864)

```python
def test_unhashed_files_removed_from_current_files(self):
    import inspect
    from vaultspec_rag.indexer import CodebaseIndexer
    source = inspect.getsource(CodebaseIndexer.incremental_index)
    assert "set(current_files) - set(current_hashes)" in source
```

**Violation:** Tautological. Tests string content of source code, not behavior.
**Verdict:** DELETE — replace with behavioral integration test that verifies unhashed files don't reappear.

---

### V2: DUAL MARKERS — tests with more than one marker

**Mandate:** "Every test must have exactly one marker."

#### V2a: `bench_rag.py` — all 5 tests have `@pytest.mark.benchmark` AND `@pytest.mark.quality`

**File:** `src/vaultspec_rag/tests/benchmarks/bench_rag.py`
**Lines:** 35-36, 56-57, 72-73, 87-88, 136-137

```python
@pytest.mark.benchmark
@pytest.mark.quality
def test_bench_embedding_throughput(model, n_docs: int = 50) -> dict:
```

**Violation:** Dual markers. `benchmark` is not even a registered marker in pyproject.toml.
**Verdict:** REWRITE — remove `@pytest.mark.quality`, keep only `@pytest.mark.performance` (the correct marker for benchmarks). Register `benchmark` or remove it.

#### V2b: Previously identified in Round 25

Per R25-M1/M2/M4, there are 10+ tests across integration test files with dual markers (`integration` + `quality`, `performance` + `unit`, etc.). These were already reported in `docs/audit/2026-03-07-tests-round25.md` with full line numbers. Not re-listed here to avoid duplication — see R25 report.

---

### V3: UNDEFINED MARKER — `@pytest.mark.benchmark`

**File:** `src/vaultspec_rag/tests/benchmarks/bench_rag.py`
**Lines:** 35, 56, 72, 87, 136

`benchmark` is not defined in `pyproject.toml` markers. Pytest will issue an `UnknownMarkWarning` in strict mode.

**Verdict:** REWRITE — either register `benchmark` in pyproject.toml or replace with `@pytest.mark.performance`.

---

## Clean Files (no violations)

All other test files pass the mandate audit:

- `src/vaultspec_rag/tests/conftest.py` — clean
- `src/vaultspec_rag/tests/constants.py` — clean (not a test file)
- `src/vaultspec_rag/tests/test_store.py` — clean
- `src/vaultspec_rag/tests/test_store_codebase.py` — clean (synthetic vectors fixed in Task #64)
- `src/vaultspec_rag/tests/test_search_unit.py` — clean (mocks removed in Task #54)
- `src/vaultspec_rag/tests/test_cli.py` — clean
- `src/vaultspec_rag/tests/test_mcp_server.py` — clean
- `src/vaultspec_rag/tests/test_embeddings.py` — clean
- `src/vaultspec_rag/tests/integration/conftest.py` — clean
- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` — clean
- `src/vaultspec_rag/tests/integration/test_search_integration.py` — clean
- `src/vaultspec_rag/tests/integration/test_store_integration.py` — clean
- `src/vaultspec_rag/tests/integration/test_embeddings.py` — clean
- `src/vaultspec_rag/tests/integration/test_quality.py` — clean (dual markers noted in R25)
- `src/vaultspec_rag/tests/integration/test_performance.py` — clean (dual markers noted in R25)
- `src/vaultspec_rag/tests/integration/test_robustness.py` — clean
- `src/vaultspec_rag/tests/integration/test_api_integration.py` — clean
- `src/vaultspec_rag/tests/integration/test_codebase_integration.py` — clean

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Banned patterns (mocks/skip/unittest) | 0 | -- |
| Synthetic embeddings | 0 | -- |
| Tautological tests (inspect.getsource) | 2 | HIGH — delete |
| Dual markers | 5 in bench_rag.py + ~10 in integration (see R25) | MEDIUM — fix |
| Undefined marker (`benchmark`) | 5 | LOW — register or replace |

**Overall:** The test suite is largely compliant. The mock/skip/unittest purge (Tasks #54, #55, #60, #61) and synthetic vector fix (Task #64) were effective. Remaining violations are 2 tautological `inspect.getsource` tests and marker hygiene issues.
