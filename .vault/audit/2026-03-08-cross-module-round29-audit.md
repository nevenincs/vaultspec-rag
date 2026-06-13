---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-08
modified: '2026-03-08'
---

# Round 29: Cross-Module Integration Audit

**Date:** 2026-03-08
**Scope:** Boundary conditions between indexer ↔ store, search ↔ store, api.py ↔ store/searcher, watcher ↔ indexer ↔ gpu_sem, CLI ↔ MCP server
**Finding Level:** 2 CRITICAL, 1 HIGH (see summary)

______________________________________________________________________

## Executive Summary

Found **2 CRITICAL race conditions** and **1 HIGH data corruption risk**:

1. **CRITICAL: Collection drop → search race window** — When `full_index(clean=True)` calls `drop_table()` then `ensure_table()`, the collection is deleted before it's recreated. If a concurrent search (via watcher → MCP tool) tries to access the collection while it's missing, Qdrant returns an error. No fallback exists.
1. **CRITICAL: Metadata loss on incremental_index exception** — `CodebaseIndexer._write_meta(current_hashes)` is called *after* upserting chunks. If `upsert_code_chunks()` succeeds but `_write_meta()` fails/throws, the next incremental run will lose change history for all unchanged files, causing them to appear brand-new on next run (duplicates + stale hashes).
1. **HIGH: VaultGraph cache not invalidated after full_index** — `api.py` calls `_graph_cache.invalidate()` only in `index()` (vault) and `index_codebase()` functions. However, if code calls `VaultIndexer.full_index()` or `CodebaseIndexer.full_index()` *directly* (not via api.py), the graph cache is never invalidated, causing stale re-ranking in subsequent `search_vault()` calls.

All other boundaries checked are correct.

______________________________________________________________________

## Detailed Findings

### 1. indexer → store boundary: Drop → recreate race window

**Location:** `src/vaultspec_rag/indexer.py:684-687` (VaultIndexer.full_index)

```python
if clean:
    self.store.drop_table()        # Line 686: Deletes collection
    self.store.ensure_table()      # Line 687: Recreates it
else:
    self.store.ensure_table()
```

**Risk:** Between `drop_table()` (line 186-190 in store.py) and `ensure_table()` (line 200+), the collection does **not exist**. If a concurrent search runs:

- Watcher thread calls `vault_indexer.incremental_index()` → `anyio.to_thread.run_sync()` (line 130 in watcher.py)
- OR MCP tool `search_vault()` is invoked → `searcher.search_vault()` (line 183 in mcp_server.py)
- Either path calls `store.hybrid_search()` (line 525 in store.py)
- `hybrid_search()` calls `ensure_table()` then `self._client.search()` on a non-existent collection

**Qdrant behavior:** Returns a collection-not-found error (e.g., `RpcError`). **No fallback or graceful error handling exists** — the error propagates to the caller. Search fails instead of returning empty results.

**Severity:** **CRITICAL**

**Mitigation:** Wrap the drop+create in a synchronous section protected by a module-level `threading.Lock`, or use `TRUNCATE` semantics (scroll + delete all points) instead of drop+create.

______________________________________________________________________

### 2. indexer → store boundary: Metadata loss on exception

**Location:** `src/vaultspec_rag/indexer.py:1218-1223` (CodebaseIndexer.incremental_index)

```python
self.store.upsert_code_chunks(all_new_chunks)  # Line 1218

# Save updated metadata (file path -> content hash).
# Use current_hashes (not current_files) as source — files that
# failed hashing are excluded so they don't cause KeyError.
self._write_meta(current_hashes)               # Line 1223
```

**Risk:**

- If `upsert_code_chunks()` succeeds (chunks written to Qdrant), but `_write_meta()` raises an exception (disk full, permission, JSON error), the metadata file is **never written**.
- On the next `incremental_index()` call, `_load_meta()` returns the **stale** hash file (or empty dict if it was never written).
- All files in `current_files` that have `modified_files` will be re-hashed and found unchanged → **added to `unchanged_files`** (line 1179).
- But files that actually didn't change are now **missing from metadata**, so they appear to be "modified by absence" on the *next* run.
- This cascades: chunks for unchanged files get re-embedded and re-upserted → **duplicate embeddings** in Qdrant.

**Details:** Looking at `_load_meta()` (line 1254-1260):

```python
def _load_meta(self) -> dict[str, str]:
    if not self._meta_path.exists():
        return {}
    try:
        return json.loads(self._meta_path.read_text(encoding="utf-8"))
    except (KeyError, ValueError, OSError):
        return {}
```

If the file was never written due to a prior exception, it stays missing, and each run resets hashes.

**Severity:** **CRITICAL** — Data corruption (duplicates) + index bloat

**Mitigation:** Use try-except to ensure metadata is written atomically *before* returning. Or write metadata to a temp file first, then rename (which is done via `os.replace` on line 1252, but the outer exception can still prevent the write attempt).

______________________________________________________________________

### 3. api.py → store/searcher boundary: Graph cache not invalidated after direct full_index calls

**Location:** `src/vaultspec_rag/api.py:95-97` (index function)

```python
engine = get_engine(root_dir)
result = engine.indexer.full_index() if full else engine.indexer.incremental_index()
_graph_cache.invalidate()  # Line 96: Invalidates after indexing
```

**vs. MCP call:** `src/vaultspec_rag/mcp_server.py:343-344` (reindex_vault tool)

```python
if clean:
    result = comp.vault_indexer.full_index(clean=True)
else:
    result = comp.vault_indexer.incremental_index()
# No _graph_cache.invalidate() call!
```

**Risk:** If code calls `VaultIndexer.full_index()` or `CodebaseIndexer.full_index()` **directly** (not via `api.py`):

1. Indexer rewrites all documents in the store
1. But the cached `VaultGraph` in `VaultSearcher._cached_graph` or `_graph_cache` is **not invalidated**
1. Next `search_vault()` call uses the stale graph for re-ranking
1. Graph relationships no longer match the indexed documents → **incorrect boosting** (docs may be missing or changed)

**Paths affected:**

- Direct calls to `engine.indexer.full_index()`
- MCP tools `reindex_vault()` and `reindex_codebase()` (lines 344, 375 in mcp_server.py) — **no invalidation call**
- Watcher calls to `incremental_index()` — less critical since incremental doesn't rebuild the graph, but full_index in watcher would have the same bug

**Severity:** **HIGH** — Stale re-ranking data, degraded search quality

**Mitigation:** Add `_graph_cache.invalidate()` call after `full_index(clean=True)` in mcp_server.py reindex tools. Or make VaultSearcher clear its own `_cached_graph` after detecting an index change (TTL-based approach already exists at line 243, but TTL is 3600s — too long for a test).

______________________________________________________________________

### 4. watcher → indexer → gpu_sem: Semaphore release on exception ✓ CORRECT

**Location:** `src/vaultspec_rag/watcher.py:129-140` (vault reindex) and `155-166` (code reindex)

```python
try:
    async with gpu_sem:
        result = await anyio.to_thread.run_sync(
            vault_indexer.incremental_index
        )
    _last_vault_index = time.monotonic()
    logger.info(...)
except Exception:
    logger.exception("Vault re-index failed")
```

**Status:** ✓ **CORRECT** — The `async with gpu_sem:` block ensures the semaphore is released even if `anyio.to_thread.run_sync()` raises an exception. The exception is caught and logged, and the watcher continues.

______________________________________________________________________

### 5. search → store boundary: Qdrant errors on missing collection during rebuild ✓ PROPAGATES CORRECTLY

**Location:** `src/vaultspec_rag/store.py:525-605` (hybrid_search)

The `hybrid_search()` method calls `ensure_table()` before searching. If the collection is missing and being recreated, `ensure_table()` will see it's already being recreated (or already recreated) and proceed. However, if the collection is deleted *between* the index rebuild start and Qdrant's internal state update, a race condition exists.

**Status:** This is folded into Finding #1 above.

______________________________________________________________________

### 6. api.py → store/searcher boundary: Engine cache thread-safety ✓ CORRECT

**Location:** `src/vaultspec_rag/api.py:59-73` (get_engine)

```python
def get_engine(root_dir: pathlib.Path) -> _Engine:
    global _engine
    root_dir = Path(root_dir).resolve()
    if _engine is not None and _engine.root_dir == root_dir:
        return _engine
    with _engine_lock:
        if _engine is not None and _engine.root_dir == root_dir:  # Double-check lock
            return _engine
        if _engine is not None:
            _engine.store.close()
        _engine = _Engine(root_dir)
    return _engine
```

**Status:** ✓ **CORRECT** — Double-check locking prevents concurrent initialization. `Path.resolve()` normalizes the path so `./project` and `project` are treated identically. `_Engine.__init__` is protected by the lock, so only one thread initializes at a time.

Note: There is **no explicit `close()`** method on `_Engine`, but it's not needed since the singleton lives for the process lifetime. For testing, `reset_engine()` (line 76) properly calls `store.close()`.

______________________________________________________________________

### 7. CLI fast-path → MCP server boundary: Initialization state ✓ CORRECT

**Location:** `src/vaultspec_rag/cli.py:376-415` (\_try_mcp_search) and mcp_server.py:51-87 (get_comp)

**CLI fast-path behavior:**

- `_try_mcp_search()` uses `asyncio.run(_call())` which creates a fresh event loop
- Inside `_call()`, it connects to MCP server via HTTP and calls `search_vault` tool
- If MCP server's `get_comp()` is still initializing, the HTTP response will either:
  - Block until initialization completes (normal case)
  - Return an error if `_comp_error` is set (line 65-67 in mcp_server.py)

**Status:** ✓ **CORRECT** — `get_comp()` caches initialization errors, so if initialization fails once, all subsequent calls fail immediately with the cached error. No "initialization in progress" state is exposed; the synchronous lock ensures atomicity.

However, there is a subtle edge case: if `search_vault` tool is called **before** `_ensure_watcher()` is invoked (line 195 in mcp_server.py), the watcher won't be started. But this is intentional — watcher is started lazily on first search.

______________________________________________________________________

## Test Coverage

**Tested boundaries:**

- ✓ api.py ↔ store (double-check lock)
- ✓ watcher ↔ gpu_sem (exception handling)
- ✓ CLI ↔ MCP (initialization state)

**Not tested (gaps):**

- ✗ drop_table → search concurrency race (no test for concurrent drop+search)
- ✗ upsert → metadata write exception (no test for write failure scenarios)
- ✗ direct full_index → graph cache invalidation (MCP calls are not tested)

______________________________________________________________________

## Recommendations

| Priority | Issue                          | Action                                                                                    | Effort |
| -------- | ------------------------------ | ----------------------------------------------------------------------------------------- | ------ |
| CRITICAL | Drop → search race             | Add threading.Lock around drop+ensure; or use TRUNCATE instead                            | Medium |
| CRITICAL | Metadata write exception       | Wrap upsert+write in try-except; ensure metadata is always written                        | Low    |
| HIGH     | Graph cache invalidation (MCP) | Add `_graph_cache.invalidate()` after full_index in mcp_server tools                      | Low    |
| MEDIUM   | Test coverage                  | Add integration tests for concurrent drop+search, write failures, direct full_index calls | Medium |

______________________________________________________________________

## Files Affected

- `src/vaultspec_rag/indexer.py` (lines 684-687, 1218-1223)
- `src/vaultspec_rag/store.py` (lines 186-198)
- `src/vaultspec_rag/mcp_server.py` (lines 343-354, 374-385)
- `src/vaultspec_rag/api.py` (lines 95-97)

______________________________________________________________________

## Conclusion

2 CRITICAL race conditions identified with high impact. The first (drop → search race) can cause immediate search failures. The second (metadata loss) can cause index corruption over time. The HIGH-priority graph cache issue degrades search quality silently.

All three are fixable with small targeted changes. Recommend prioritizing CRITICAL issues first, then adding integration tests for the affected code paths.
