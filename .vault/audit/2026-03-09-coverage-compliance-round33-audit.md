---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-09
related: []
---

# Round 33: Integration Test Coverage Gap & Compliance Audit

**Date:** 2026-03-09
**Status:** COMPLETE
**Findings:** 100% COMPLIANCE + 5 COVERAGE GAPS (2 CRITICAL)

---

## Part 1: Compliance Check — 100% PASS

### Scope

Audited all test files:

- **Unit tests:** `src/vaultspec_rag/tests/test_*.py` (8 files)
- **Integration tests:** `src/vaultspec_rag/tests/integration/test_*.py` (11 files)
- **Fixtures:** `src/vaultspec_rag/tests/conftest.py` + `src/vaultspec_rag/tests/integration/conftest.py`

### Violations Checked

✅ **NO** `unittest.mock`, `MagicMock`, `@patch` decorators
✅ **NO** `monkeypatch` fixture usage
✅ **NO** `pytest.skip()` or `@pytest.mark.skip`
✅ **NO** `import unittest` statements
✅ **NO** Tautological tests (asserting True, asserting pre-set values)
✅ **NO** Tests without assertions

### Result

**100% COMPLIANCE** — All test files strictly follow CLAUDE.md standards.

---

## Part 2: Coverage Gap Analysis

### Critical Gaps (MUST ADD TESTS)

#### **GAP 1: CRITICAL** — VaultIndexer.full_index(clean=True) NOT TESTED IN INTEGRATION

**Location:** `src/vaultspec_rag/indexer.py:full_index(clean=True)`
**Current Status:** ❌ NO integration test

**What happens:**

```python
def full_index(self, clean: bool = False) -> IndexResult:
    if clean:
        self.store.drop_table()      # ← Deletes entire collection
        # Rebuilds from scratch
```

**Why this is critical:**

- Concurrent search + drop collection = race condition (R29-C1 CRITICAL issue)
- If `full_index(clean=True)` drops while search is reading, search fails
- No test exercises this scenario

**Current tests:**

- `test_double_full_index_idempotent()` — calls `full_index()` but NOT with `clean=True`
- Fixture setup calls `indexer.full_index()` (default `clean=False`)

**What's needed:**

- Test `full_index(clean=True)` creates fresh empty collection
- Test idempotence: `full_index(clean=True)` twice → same document count

---

#### **GAP 2: CRITICAL** — CodebaseIndexer.full_index(clean=True) NOT TESTED IN INTEGRATION

**Location:** `src/vaultspec_rag/indexer.py:CodebaseIndexer.full_index(clean=True)`
**Current Status:** ❌ NO integration test

**What happens:**

```python
def full_index(self, clean: bool = False) -> IndexResult:
    if clean:
        self.store.drop_code_table()  # ← Deletes codebase collection
```

**Why this is critical:**

- Same race condition as VaultIndexer
- Concurrent search_codebase + drop → missing collection error

**Current tests:**

- `test_full_index_idempotent()` — calls `full_index()` with default `clean=False`
- No call to `full_index(clean=True)`

**What's needed:**

- Test `full_index(clean=True)` on codebase
- Verify idempotence after clean rebuild

---

#### **GAP 3: HIGH** — reindex_vault MCP Tool NOT TESTED IN INTEGRATION

**Location:** `src/vaultspec_rag/mcp_server.py:reindex_vault()`
**Current Status:** ❌ NO integration test (only unit ADR check in test_adr_regression.py)

**What happens:**

```python
async def reindex_vault(root: str, full: bool = False, clean: bool = False):
    # Calls VaultIndexer.full_index(clean=clean) → calls store.drop_table()
    # Then calls _graph_built_at = 0.0 to invalidate cache
```

**What we're missing:**

- Full end-to-end test via MCP server (not just API)
- Test that graph cache is actually invalidated after MCP reindex
- Test with `clean=True` flag

**Current tests:**

- `test_reindex_vault_resets_graph_cache()` in test_adr_regression.py — reads source code only, doesn't run it

---

#### **GAP 4: HIGH** — reindex_codebase MCP Tool NOT TESTED IN INTEGRATION

**Location:** `src/vaultspec_rag/mcp_server.py:reindex_codebase()`
**Current Status:** ❌ NO integration test

**What happens:**

- Same as reindex_vault but for codebase
- Calls `CodebaseIndexer.full_index(clean=clean)` + invalidates graph cache

**What we're missing:**

- Integration test calling MCP tool

---

#### **GAP 5: MEDIUM** — get_code_file MCP Tool NOT TESTED IN INTEGRATION

**Location:** `src/vaultspec_rag/mcp_server.py:get_code_file()`
**Current Status:** ❌ NO integration test

**What happens:**

```python
async def get_code_file(root: str, path: str) -> str:
    # Returns full source code content for a file
    # Used by Claude to read files referenced in code search results
```

**What we're missing:**

- Test that retrieves a real source file from test-project/src/
- Test error handling for nonexistent files

---

### Secondary Gaps (NICE-TO-HAVE)

#### **GAP 6: LOW** — watcher module (watch_and_reindex) NOT TESTED

**Location:** `src/vaultspec_rag/watcher.py`
**Current Status:** ❌ ZERO integration test coverage

**What happens:**

- Filesystem watcher using `watchfiles`
- Triggers incremental indexing on file changes

**Why it's lower priority:**

- Relies on async event loop + file system events
- Difficult to test in pytest without mocking (which we can't do)
- Could use manual integration test in docs/

---

#### **GAP 7: LOW** — VaultSearcher.search_all() MCP TOOL INTEGRATION

**Location:** `src/vaultspec_rag/mcp_server.py:search_all()`
**Current Status:** ⚠️ PARTIAL COVERAGE

- `test_search_all_returns_mixed_results()` in test_search_integration.py — tests via VaultSearcher
- NO test via MCP server endpoint

**Current coverage:**

```python
# ✓ Tested: Direct VaultSearcher API
searcher.search_all("query", top_k=10)

# ✗ NOT tested: MCP server endpoint
# async def search_all(root, query, top_k, ...)
```

---

## Part 3: Integration Test Structure Summary

### Test Files and What They Cover

| Test File | Scope | Markers | Key Methods Tested |
|-----------|-------|---------|-------------------|
| **test_indexer_integration.py** | Vault indexing | `@pytest.mark.integration` | `full_index()`, `incremental_index()` (both default clean=False) |
| **test_codebase_integration.py** | Code indexing | `@pytest.mark.integration` | `full_index()` (no clean=True test), `incremental_index()` |
| **test_search_integration.py** | Search & rerank | `@pytest.mark.integration` | `search()`, `search_vault()`, `search_codebase()`, `search_all()` (API) |
| **test_store_integration.py** | Qdrant ops | `@pytest.mark.integration` | `hybrid_search()`, `delete_documents()`, `context_manager` |
| **test_api_integration.py** | Public facade | `@pytest.mark.integration` | `search()`, `index()`, `list_documents()`, `get_related()`, engine singleton |
| **test_cli_integration.py** | CLI commands | `@pytest.mark.integration` | `status`, `index`, `search` subcommands (subprocess) |
| **test_quality.py** | Ranking quality | `@pytest.mark.quality` | Known-answer precision, filter correctness, authority boost |
| **test_performance.py** | Latency/resource | `@pytest.mark.performance` | Query latency, graph cache reuse, FTS rebuild |
| **test_robustness.py** | Edge cases | `@pytest.mark.robustness` | Stories without frontmatter, nonstandard metadata, orphan docs |
| **test_embeddings.py** | GPU inference | `@pytest.mark.integration` | Qwen3 dense + SPLADE sparse encoding, document-query similarity |

### Code Paths NOT Exercised in Integration

| Code Path | Tested? | Location |
|-----------|---------|----------|
| `VaultIndexer.full_index(clean=True)` | ❌ No | indexer.py:87 |
| `CodebaseIndexer.full_index(clean=True)` | ❌ No | indexer.py:256 |
| `VaultStore.drop_table()` | ⚠️ Partial | Called in full_index(clean=True), not tested standalone |
| `VaultStore.drop_code_table()` | ⚠️ Partial | Called in CodebaseIndexer, not tested |
| MCP `reindex_vault()` endpoint | ❌ No | mcp_server.py:152 |
| MCP `reindex_codebase()` endpoint | ❌ No | mcp_server.py:173 |
| MCP `get_code_file()` endpoint | ❌ No | mcp_server.py:192 |
| MCP `search_all()` endpoint | ❌ No | mcp_server.py:106 (API tested, not MCP) |
| `watch_and_reindex()` watcher | ❌ No | watcher.py:1 |
| `VaultSearcher._rerank()` with reranker enabled | ✓ Yes | test_search_integration.py:377-418 |

---

## Fixture Quality Assessment

### Strengths ✅

- **Isolation:** 5 unique `.qdrant-*` suffixes prevent fixture cross-contamination
- **GPU efficiency:** Shared `embedding_model` fixture avoids duplicate model loads (~900MB each)
- **Real inference:** All tests use GPU embeddings (Qwen3-Embedding-0.6B), no synthetic vectors
- **Corpus coverage:** `GPU_FAST_CORPUS_STEMS` (13 docs) covers all 5 doc_types
- **Session-scoped:** `rag_components` built once per test session, reused across tests

### Issues ⚠️

- ⚠️ No fixtures accept `clean=True` parameter for testing collection drops
- ⚠️ `rag_components_with_code` hardcoded to index test-project/src/ (not parameterizable)

---

## Summary of Findings

### **COMPLIANCE AUDIT: ✅ 100% PASS**

- All 19 test files follow CLAUDE.md standards strictly
- Zero violations of mock/patch/skip/unittest rules
- Zero tautological tests

### **COVERAGE GAP AUDIT**

| Gap # | Severity | Issue | Location |
|-------|----------|-------|----------|
| 1 | CRITICAL | `VaultIndexer.full_index(clean=True)` untested | indexer.py:87 |
| 2 | CRITICAL | `CodebaseIndexer.full_index(clean=True)` untested | indexer.py:256 |
| 3 | HIGH | MCP `reindex_vault()` endpoint untested | mcp_server.py:152 |
| 4 | HIGH | MCP `reindex_codebase()` endpoint untested | mcp_server.py:173 |
| 5 | HIGH | MCP `get_code_file()` endpoint untested | mcp_server.py:192 |
| 6 | MEDIUM | MCP `search_all()` endpoint untested (API tested) | mcp_server.py:106 |
| 7 | LOW | watcher `watch_and_reindex()` untested | watcher.py:1 |

---

## Recommended Actions

### Priority 1: CRITICAL — Add clean=True tests

1. **test_indexer_integration.py**: Add `test_full_index_clean_drops_and_rebuilds()`
   - Call `full_index(clean=True)`
   - Verify empty → indexed documents flow
   - Verify idempotence: second `full_index(clean=True)` same count

2. **test_codebase_integration.py**: Add `test_full_index_clean_drops_code_and_rebuilds()`
   - Same as above for codebase

### Priority 2: HIGH — Add MCP endpoint integration tests

1. **New test class in test_cli_integration.py or test_api_integration.py**:
   - `test_mcp_reindex_vault_invalidates_graph()`
   - `test_mcp_reindex_codebase_invalidates_graph()`
   - `test_mcp_get_code_file_returns_content()`
   - `test_mcp_get_code_file_nonexistent_error()`
   - `test_mcp_search_all_endpoint()`

### Priority 3: LOW — Watcher integration

1. Document in **docs/research/** that watcher testing requires:
   - Manual integration test setup (watchfiles not pytest-mockable)
   - Or isolated test with real file system

---

## Audit Quality

- ✅ Read all 19 test files (8 unit, 11 integration)
- ✅ Read 2 conftest.py files (global + integration fixtures)
- ✅ Grepped all files for mock/patch/skip/unittest violations
- ✅ Verified pytest markers (unit, integration, quality, performance, robustness)
- ✅ Identified 7 coverage gaps with specific locations
- ✅ Cross-referenced against CLAUDE.md mandatory standards
