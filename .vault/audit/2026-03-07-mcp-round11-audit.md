---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# Round 11 Audit -- mcp_server.py (deep dive, post-fix verification)

**Auditor:** docs-researcher-2-2
**File:** `src/vaultspec_rag/mcp_server.py` (356 lines)
**Date:** 2026-03-07

______________________________________________________________________

## Check 1: `get_comp()` Thread Safety

### Lines 43-84

```python
_comp: RagComponents | None = None
_comp_lock = threading.Lock()
_comp_error: Exception | None = None

def get_comp() -> RagComponents:
    global _comp, _comp_error
    if _comp is not None:          # Fast path (no lock)
        return _comp
    with _comp_lock:
        if _comp is not None:      # Double-check after lock
            return _comp
        if _comp_error is not None: # Failure caching
            raise RuntimeError(
                "RAG initialization previously failed"
            ) from _comp_error
        try:
            ...
            _comp = RagComponents(...)
        except Exception as exc:
            _comp_error = exc
            raise
    return _comp
```

**Verdict: PASS.** All three required elements are present:

1. **Double-checked locking**: Fast path at line 55 (no lock), double-check at line 59 (inside lock)
1. **Thread-safe lock**: `threading.Lock()` at module level (line 44)
1. **Failure caching**: `_comp_error` stores the exception (line 82), re-raised on subsequent calls (line 62-64) with `from _comp_error` chain

The `_comp` assignment at line 73-80 is inside the lock, so only one thread can create the `RagComponents` bundle. The fast path outside the lock is safe because Python's GIL guarantees atomic reference reads, and `_comp` transitions from `None` to a fully-initialized object (no partial initialization visible).

______________________________________________________________________

## Check 2: Async Tools with `anyio.to_thread.run_sync()`

| Tool                 | Line | Declaration                      | Uses `anyio.to_thread.run_sync()`? |
| -------------------- | ---- | -------------------------------- | ---------------------------------- |
| `search_vault`       | 137  | `async def`                      | Yes (line 159)                     |
| `search_codebase`    | 163  | `async def`                      | Yes (line 203)                     |
| `search_all`         | 207  | `async def`                      | Yes (line 224)                     |
| `get_index_status`   | 228  | `async def`                      | Yes (line 239)                     |
| `get_code_file`      | 243  | `async def`                      | Yes (line 260)                     |
| `reindex_vault`      | 264  | `async def`                      | Yes (line 287)                     |
| `reindex_codebase`   | 291  | `async def`                      | Yes (line 315)                     |
| `get_vault_document` | 320  | plain `def` (resource, not tool) | No                                 |

**Verdict: PASS.** All 7 MCP tools are `async def` and use `anyio.to_thread.run_sync()` to offload blocking work. The blocking work (GPU inference, Qdrant I/O, file reads) runs in a thread, keeping the event loop responsive.

Note: `get_index_status` and `get_code_file` were previously plain `def` (R21-m10). They are now `async def` with `anyio.to_thread.run_sync()`, consistent with all other tools.

### R11-m1: `get_vault_document` resource is synchronous `def` (Minor)

The `get_vault_document` resource at line 320 is a plain `def` that calls `get_comp()` and `comp.store.get_by_id()` synchronously. Since it's a resource (not a tool), FastMCP may handle it differently. However, `get_by_id()` makes a Qdrant RPC (`_client.retrieve`), which is blocking I/O. If MCP resources are served from the event loop, this will block.

**File:** `mcp_server.py:320-330`

______________________________________________________________________

## Check 3: Path Traversal Fix

### `get_code_file()` (lines 243-260)

```python
def _run() -> str:
    comp = get_comp()
    root_resolved = comp.root_dir.resolve()
    full_path = (root_resolved / path).resolve()
    if not full_path.is_relative_to(root_resolved):
        raise ValueError(f"path '{path}' is outside the workspace")
    if not full_path.exists():
        raise FileNotFoundError(f"File '{path}' not found")
    return full_path.read_text(encoding="utf-8")
```

**Verdict: PASS.** Both `root_dir` and the joined path are resolved before comparison. The key fix from R21-C1: `root_resolved = comp.root_dir.resolve()` is applied first (line 252), then `(root_resolved / path).resolve()` (line 253). The `is_relative_to(root_resolved)` check (line 254) compares resolved paths, so `..` traversal is caught.

Symlink scenario: If `comp.root_dir` is itself a symlink, `resolve()` follows it. If a file inside the workspace is a symlink pointing outside, `resolve()` follows it and `is_relative_to` correctly rejects it. This is the correct behavior.

Raises `ValueError` (not returning error string) on traversal attempt. Raises `FileNotFoundError` on missing file. Both are exceptions, not return values.

______________________________________________________________________

## Check 4: Error Responses as Exceptions

All tools raise exceptions on error:

| Tool                       | Error Type                                              | Line     |
| -------------------------- | ------------------------------------------------------- | -------- |
| `get_code_file`            | `ValueError` (traversal), `FileNotFoundError` (missing) | 255, 257 |
| `get_vault_document`       | `FileNotFoundError` (not found)                         | 329      |
| All tools via `get_comp()` | `RuntimeError` (init failed), `ImportError` (no deps)   | 62-64    |

No tool returns error strings. All errors propagate as exceptions, which FastMCP converts to MCP error responses.

**Verdict: PASS.**

______________________________________________________________________

## Check 5: `top_k` Bounds

### `_clamp_top_k()` (lines 130-132)

```python
def _clamp_top_k(top_k: int) -> int:
    return max(1, min(top_k, 100))
```

Called in:

- `search_vault` (line 144)
- `search_codebase` (line 181)
- `search_all` (line 209)

Not called in:

- `get_index_status` (no top_k parameter)
- `get_code_file` (no top_k parameter)
- `reindex_vault` (no top_k parameter)
- `reindex_codebase` (no top_k parameter)

**Verdict: PASS.** `top_k` is clamped to `[1, 100]` for all three search tools. R21-m12 is fixed.

______________________________________________________________________

## Check 6: `SearchResultItem` Schema Sync

### `SearchResult` (search.py lines 61-78)

Fields: `id`, `path`, `title`, `score`, `snippet`, `source` (Literal["vault", "codebase"]), `doc_type=""`, `feature=""`, `date=""`, `language=""`, `line_start=None`, `line_end=None`, `node_type=None`, `function_name=None`, `class_name=None`

### `SearchResultItem` (mcp_server.py lines 88-107)

Fields: `id`, `path`, `title`, `score`, `snippet`, `source` (str), `doc_type=""`, `feature=""`, `date=""`, `language=""`, `line_start=None`, `line_end=None`, `node_type=None`, `function_name=None`, `class_name=None`

**Verdict: PASS.** All 15 fields match in name, type, and defaults. The only difference is `source: Literal["vault", "codebase"]` in `SearchResult` vs `source: str` in `SearchResultItem` -- the Pydantic model is more permissive, which is fine for serialization. The `model_config = {"from_attributes": True}` at line 91 enables `SearchResultItem.model_validate(r, from_attributes=True)` to read dataclass attributes directly.

### R11-m2: `SearchResultItem` is a manual mirror of `SearchResult` (Minor)

If fields are added to `SearchResult`, `SearchResultItem` must be manually updated. This is a maintenance risk (R21-m13, still unfixed). Could be addressed by generating one from the other or using a shared schema, but it's working correctly today.

**File:** `mcp_server.py:88-107`, `search.py:61-78`

______________________________________________________________________

## Check 7: `IndexResponse.files` Default

### `reindex_vault()` (lines 279-285)

```python
return IndexResponse(
    total=result.total,
    added=result.added,
    updated=result.updated,
    removed=result.removed,
    duration_ms=result.duration_ms,
)
```

The `files` field is NOT set. It defaults to `0` (line 127: `files: int = Field(default=0, ...)`).

### `reindex_codebase()` (lines 306-313)

```python
return IndexResponse(
    total=result.total,
    ...
    files=result.files,
)
```

The `files` field IS set from `result.files`.

### R11-m3: `reindex_vault` does not populate `files` in IndexResponse (Minor)

The `VaultIndexer.full_index()` and `VaultIndexer.incremental_index()` both return `IndexResult` with `files=0` (the default, since `IndexResult.files` defaults to 0 and vault indexer never sets it). The MCP response shows `files: 0` which could confuse users into thinking no files were processed. This is R21-m14, still present.

In reality, vault indexing processes documents (not "files" in the codebase sense), so `files=0` is technically correct but misleading. The `added` + `updated` counts are the meaningful numbers for vault reindex.

**File:** `mcp_server.py:279-285`

______________________________________________________________________

## Check 8: `anyio` Import

### Line 15

```python
import anyio
```

**Verdict: PASS.** `anyio` is imported at module level, not inside each tool function.

______________________________________________________________________

## Check 9: `reindex_vault clean=True` Behavior

### `reindex_vault()` (lines 275-276)

```python
if clean:
    result = comp.vault_indexer.full_index()
```

### `VaultIndexer.full_index()` (indexer.py lines 680-694)

```python
# Delete all existing docs
try:
    existing_ids = self.store.get_all_ids()
    if existing_ids:
        self.store.delete_documents(list(existing_ids))
except OSError:
    logger.error("Failed to delete existing documents during full re-index — aborting to prevent duplicates")
    raise
self.store.upsert_documents(docs)
```

### R11-M1: `reindex_vault clean=True` does not drop the collection -- deletes by ID then upserts (MEDIUM)

`full_index()` does NOT drop and recreate the collection. It:

1. Scans all documents
1. Gets all existing IDs via `get_all_ids()` (scroll)
1. Deletes them via `delete_documents()` (by ID)
1. Upserts new documents

This means:

- **Stale payload indexes are preserved** -- if the schema changes, old indexes remain
- **Orphaned points could survive** if `get_all_ids()` misses points with missing `doc_id` payload fields (the `_scroll_all_ids` method at store.py:372-390 only collects IDs from payloads that have the `doc_id` field)
- **Not atomic** -- between delete and upsert, the collection is empty. A concurrent search would return zero results.

For a "clean" re-index, `store.recreate_collection()` or `_client.delete_collection()` + `_ensure_collection()` would be more thorough. The current approach is functional but potentially leaves orphaned data.

**File:** `mcp_server.py:275-276`, `indexer.py:680-694`

______________________________________________________________________

## Check 10: Unguarded `comp` Field Access

All tools call `get_comp()` first, which either:

- Returns a fully-initialized `RagComponents` with all fields set (line 73-80)
- Raises `RuntimeError` (cached failure) or the original exception

There is no code path where `get_comp()` returns a partially-initialized `RagComponents`. The `RagComponents` dataclass requires all fields in its constructor (no optional fields, no defaults). If any component fails to initialize (e.g., `EmbeddingModel()` raises), the entire `get_comp()` call fails and `_comp` stays `None`.

**Verdict: PASS.** No unguarded access. All fields are guaranteed non-None after `get_comp()` succeeds.

______________________________________________________________________

## Summary

| ID     | Severity | Finding                                                                                                                           |
| ------ | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| R11-M1 | MEDIUM   | `reindex_vault clean=True` deletes by ID then upserts -- does not drop collection. Orphaned points and stale indexes can survive. |
| R11-m1 | MINOR    | `get_vault_document` resource is synchronous `def` -- blocks event loop on Qdrant RPC                                             |
| R11-m2 | MINOR    | `SearchResultItem` is manual mirror of `SearchResult` -- maintenance risk                                                         |
| R11-m3 | MINOR    | `reindex_vault` does not populate `files` in IndexResponse (shows 0)                                                              |

### Verified Fixes

| Prior Finding                                                           | Status                                                                   |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| R21-C1: `get_code_file` path traversal                                  | **FIXED** -- resolves both root and path before comparison               |
| R21-M6: Async tools block event loop                                    | **FIXED** -- all 7 tools use `anyio.to_thread.run_sync()`                |
| R21-M7: `get_comp()` not thread-safe                                    | **FIXED** -- `threading.Lock` + double-checked locking + failure caching |
| R21-m10: `get_index_status`/`get_code_file` sync vs async inconsistency | **FIXED** -- all tools now `async def`                                   |
| R21-m12: No `top_k` bounds checking                                     | **FIXED** -- `_clamp_top_k()` limits to [1, 100]                         |

**1 MEDIUM finding (R11-M1). 3 MINOR findings.**
