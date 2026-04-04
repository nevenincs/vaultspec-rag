---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# api.py and ADR Regression Tests Audit

Date: 2026-03-07
Auditor: docs-researcher-2-2

______________________________________________________________________

## Part A: api.py Audit

File: `src/vaultspec_rag/api.py` (252 lines)

### 1. `get_engine()` path resolution

**ISSUE (MEDIUM):** `get_engine()` at line 57 compares `_engine.root_dir != root_dir` directly. It does NOT call `Path.resolve()` on root_dir before comparison or before using it as a cache key.

This means `get_engine(Path("./myproject"))` and `get_engine(Path("myproject"))` will create TWO separate engines (two GPU model loads, two Qdrant connections), despite pointing to the same directory.

**FIX NEEDED:** Add `root_dir = root_dir.resolve()` at the top of `get_engine()`.

### 2. `get_engine()` old store cleanup

**OK.** Lines 58-59 correctly call `_engine.store.close()` before replacing the engine:

```python
if _engine is not None:
    _engine.store.close()
```

This prevents Qdrant client resource leaks when switching root dirs.

### 3. `VaultGraph` cache

**OK.** `_GraphCache` class (lines 191-225) implements:

- Thread-safe access with `threading.Lock()` (line 197)
- Double-check locking pattern (lines 201-204)
- Explicit `invalidate()` method (lines 218-222)
- `index()` calls `_graph_cache.invalidate()` after reindex (line 84)
- `index_codebase()` does NOT invalidate the graph cache (line 100-103) -- this is correct since codebase changes don't affect vault graph

### 4. `search_all()` exposure

**OK.** `search_all` is in `__all__` at line 33 and implemented at lines 158-172.

### 5. `get_related()` None contract

**ISSUE (LOW):** `get_related()` returns `None` in two cases:

1. Graph build fails (line 241): returns `None`
1. doc_id not found in graph (line 245): returns `None`

The return type annotation says `dict | None` (line 228), which is consistent. However, returning `None` when the graph fails silently hides errors. Callers must distinguish "doc not found" from "graph broken" -- both return `None`.

The task asked if it should return `[]` -- it returns `None`, not `[]`. The current behavior is documented in the docstring ("or None if the document is not found") so it's internally consistent, but the graph-failure case is not mentioned.

### 6. Bare `except Exception`

**ISSUE (LOW):** Line 211 in `_GraphCache.get()`:

```python
except Exception:
    logger.warning("Failed to build vault graph", exc_info=True)
```

This catches all exceptions including `KeyboardInterrupt` subclasses that inherit from `BaseException` (actually `Exception` does not catch those). The catch is broad but `exc_info=True` logs the full traceback. Acceptable for a graph build that can fail for many reasons (filesystem, parsing, etc.), but could be narrowed to `OSError, ValueError, ImportError`.

### 7. Resource leaks

**ISSUE (MEDIUM):** `get_engine()` is NOT thread-safe. No lock protects the `_engine` global. Two concurrent calls could both see `_engine is None`, both create engines, and the first engine's store never gets closed.

Compare with `_GraphCache.get()` which correctly uses a lock. `get_engine()` should use the same pattern.

Also: `_Engine.__init__()` does not have cleanup on partial init failure. If `EmbeddingModel()` raises (e.g., no GPU), the `VaultStore` created on line 44 is leaked (never closed).

### Summary: api.py

| #   | Issue                                                                             | Severity |
| --- | --------------------------------------------------------------------------------- | -------- |
| 1   | `get_engine()` doesn't `resolve()` root_dir -- duplicate engines for `./x` vs `x` | MEDIUM   |
| 2   | `get_engine()` not thread-safe -- race on `_engine` global                        | MEDIUM   |
| 3   | `_Engine.__init__` leaks VaultStore on partial init failure                       | LOW      |
| 4   | `get_related()` returns None for both "not found" and "graph broken"              | LOW      |
| 5   | Bare `except Exception` in `_GraphCache.get()`                                    | LOW      |

______________________________________________________________________

## Part B: ADR Regression Tests Audit

File: `src/vaultspec_rag/tests/test_adr_regression.py` (164 lines)

### Tests found: 4 of 10

Only 4 of the 10 expected ADR regression test classes exist:

| #   | ADR Decision               | Test Class               | Status            |
| --- | -------------------------- | ------------------------ | ----------------- |
| 1   | blake2b file hashing       | `TestBlake2bFileHashing` | Present           |
| 2   | score normalization        | `TestScoreNormalization` | Present           |
| 3   | path.resolve engine cache  | —                        | **MISSING**       |
| 4   | VaultGraph cache singleton | —                        | **MISSING**       |
| 5   | MCP sync tools             | `TestMCPSyncTools`       | Present           |
| 6   | Qwen3 no document prompt   | —                        | **MISSING**       |
| 7   | threading lock singleton   | —                        | **MISSING**       |
| 8   | model names/dtype          | `TestRerankerModelName`  | Present (partial) |
| 9   | filter-on-prefetch         | —                        | **MISSING**       |
| 10  | manual node walking        | —                        | **MISSING**       |

### Analysis of existing tests

#### 1. TestBlake2bFileHashing (lines 16-58)

- **Tests ADR decision?** YES -- verifies `hashlib.file_digest(f, "blake2b")` produces 128-char hex (blake2b), not 64-char (sha256).
- **Would fail if reversed?** YES -- sha256 produces 64 chars, this asserts 128.
- **Uses real code?** YES -- calls real `hashlib.file_digest`, real `_write_meta`/`_load_meta`.
- **Verdict: PASS**

#### 2. TestMCPSyncTools (lines 61-111)

- **Tests ADR decision?** YES -- verifies all 7 MCP tool functions are sync (not async coroutines).
- **Would fail if reversed?** YES -- `asyncio.iscoroutinefunction` would return True for async def.
- **Uses real code?** YES -- imports actual functions from mcp_server.py.
- **Verdict: PASS**

#### 3. TestScoreNormalization (lines 114-151)

- **Tests ADR decision?** YES -- verifies `_normalize_minmax` produces scores in [0, weight] range, and handles all-same-score edge case.
- **Would fail if reversed?** YES -- removing normalization would leave raw scores outside [0,1].
- **Uses real code?** YES -- calls real `_normalize_minmax` with real `SearchResult` objects.
- **Verdict: PASS**

#### 4. TestRerankerModelName (lines 154-163)

- **Tests ADR decision?** PARTIALLY -- verifies config default is `BAAI/bge-reranker-v2-m3`.
- **ISSUE:** CLAUDE.md says the reranker model is `cross-encoder/ms-marco-MiniLM-L6-v2`, but `config.py` line 29 and this test both say `BAAI/bge-reranker-v2-m3`. **Either CLAUDE.md is outdated or the config/test are wrong.** The test matches the actual implementation (config.py), but contradicts CLAUDE.md.
- **Would fail if reversed?** YES -- different model name would fail the assertion.
- **Uses real code?** YES -- calls real `get_config()`.
- **Missing assertions:** Does not verify dense model name (`Qwen/Qwen3-Embedding-0.6B`), sparse model name (`naver/splade-v3`), or `torch_dtype=float16`.
- **Verdict: PARTIAL PASS -- test is correct for config but CLAUDE.md mismatch needs resolution**

### Missing tests (6 of 10)

#### 3. path.resolve engine cache -- MISSING

Should test: `get_engine(Path("./x"))` and `get_engine(Path("x"))` return same engine.
Note: This test would currently FAIL because api.py doesn't call `resolve()` (see Part A finding #1).

#### 4. VaultGraph cache singleton -- MISSING

Should test: `_graph_cache.get(root)` returns same instance twice, new instance after `invalidate()`.

#### 6. Qwen3 no document prompt -- MISSING

Should test: `EmbeddingModel.encode_documents()` does NOT pass `prompt_name` to `model.encode()`.

#### 7. threading lock singleton -- MISSING

Should test: concurrent `get_comp()` calls in mcp_server.py return same `RagComponents` instance.

#### 9. filter-on-prefetch -- MISSING

Should test: `Prefetch` uses `filter=` param, not `query_filter=` on top-level `query_points`.

#### 10. manual node walking -- MISSING

Should test: `ASTChunker` uses `child_by_field_name("name")` not tree-sitter Query API.

### Additional finding

**ISSUE (MEDIUM): Reranker model mismatch between CLAUDE.md and implementation**

- CLAUDE.md says: `CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2", device="cuda")`
- config.py default: `"reranker_model": "BAAI/bge-reranker-v2-m3"`
- search.py line 211: `CrossEncoder(self._reranker_model_name, device="cuda")` -- uses config value
- test_adr_regression.py line 162: asserts `cfg.reranker_model == "BAAI/bge-reranker-v2-m3"`

The implementation and test agree with each other but disagree with CLAUDE.md. One of them needs updating.

______________________________________________________________________

## Overall Summary

| Category  | Issue                                             | Severity |
| --------- | ------------------------------------------------- | -------- |
| api.py    | `get_engine()` no `resolve()` on root_dir         | MEDIUM   |
| api.py    | `get_engine()` not thread-safe                    | MEDIUM   |
| api.py    | `_Engine.__init__` leaks store on partial failure | LOW      |
| ADR tests | 6 of 10 ADR regression tests missing              | HIGH     |
| ADR tests | Reranker model mismatch: CLAUDE.md vs config.py   | MEDIUM   |
