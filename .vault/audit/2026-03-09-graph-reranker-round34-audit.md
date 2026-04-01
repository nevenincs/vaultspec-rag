---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-09
related: []
---

# Round 34 Audit: Graph Cache Integrity and CrossEncoder Reranker Safety

**Date:** 2026-03-09
**Auditor:** Claude Code (agent-mode)
**Scope:** watcher.py, search.py, mcp_server.py

---

## Investigation 1: Watcher → Graph Cache Invalidation Gap

**FINDING SEVERITY:** CRITICAL

### Analysis

The watcher.py file (lines 118–142) monitors vault documentation changes and calls `vault_indexer.incremental_index()` when changes are detected (line 131). Similarly, code changes trigger `code_indexer.incremental_index()` (line 157).

However, **the watcher does NOT invalidate the VaultSearcher's graph cache**. Specifically:

- **VaultSearcher._graph_built_at**: Initialized to `0.0` (search.py:190)
- **Invalidation path exists**: mcp_server.py line 365 sets `comp.searcher._graph_built_at = 0.0` after `reindex_vault()`
- **Watcher gap**: watcher.py calls `vault_indexer.incremental_index()` with no subsequent cache invalidation

### Scenario

1. User modifies a vault file (e.g., add/edit an ADR)
2. Watcher detects change (watcher.py line 111) and calls `vault_indexer.incremental_index()` (line 131)
3. Vault index is updated in Qdrant
4. User immediately searches with `search_vault()` (MCP tool, mcp_server.py:184)
5. VaultSearcher checks `_graph_built_at`: if last graph was built <300s ago, it uses the **stale cached graph** (search.py:243–246)
6. Graph boost scores ignore the newly indexed ADR until TTL (300s) expires

### Root Cause

The watcher bypasses the MCP reindex tools, which are the only places that invalidate `_graph_built_at`. Incremental indexing via the watcher does not reset the graph cache.

### Impact

- **Correctness issue**: Searches for newly added/modified ADRs get stale graph-boost scores for up to 300 seconds
- **User-visible**: If a user modifies an ADR and immediately searches, the new content may not rank as high as expected due to stale graph linkage
- **Probability**: High — common workflow is to edit a doc, then search immediately

---

## Investigation 2: CrossEncoder Reranker — No OOM Backoff

**FINDING SEVERITY:** HIGH

### Analysis

In search.py, the `_rerank()` method (lines 222–237) calls:

```python
scores = reranker.predict(pairs, batch_size=32)  # line 233
```

**Findings:**

1. **batch_size=32 is hardcoded** (search.py:233)
   - Not pulled from config (config.py has no `reranker_batch_size`)
   - Not configurable at runtime

2. **No torch.cuda.OutOfMemoryError catch**
   - No try/except around `predict()` call
   - embeddings.py has exponential backoff for OOM (lines 234–250 in embeddings.py excerpt)
   - search.py reranker has no similar protection

3. **Theoretical safety at current batch_size**
   - `_clamp_top_k()` limits results to 100 (mcp_server.py:167–169)
   - Max pairs: 100 (query, snippet) pairs
   - BGE-reranker-v2-m3 at batch_size=32: processes in 4 batches
   - On typical GPU (4080 16GB, RTX 4090): safe
   - **BUT** this is not documented and no safeguard prevents future misuse

### Code Path

```
mcp_server.py:184 search_vault()
  → search.py:253 VaultSearcher.search_vault()
    → search.py:292 _rerank(query_text, results, top_k)
      → search.py:233 reranker.predict(pairs, batch_size=32)  [NO OOM CATCH]
```

### Risk

- If someone calls `searcher._rerank(query, huge_result_list, top_k=1000)` directly (bypassing MCP clamping), reranker OOM will crash
- If batch_size=32 is too large for a lower-VRAM GPU, no fallback exists
- No audit trail or logging of actual batch memory usage

### Contrast with embeddings.py

embeddings.py lines 234–250:

```python
while True:
    try:
        embeddings = self._dense_model.encode(
            truncated,
            batch_size=batch_size,
            ...
        )
        return np.asarray(embeddings, dtype=np.float32)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if batch_size <= 1:
            raise
        batch_size = max(1, batch_size // 2)
        logger.warning("CUDA OOM during dense encoding, retrying with batch_size=%d", ...)
```

reranker has no equivalent fallback.

---

## Investigation 3: Graph Cache Thread Safety

**FINDING SEVERITY:** MEDIUM

### Analysis

`_cached_graph` and `_graph_built_at` are plain attributes on VaultSearcher (search.py:189–190), accessed/modified in `_get_graph()` (lines 239–251):

```python
def _get_graph(self) -> VaultGraph | None:
    now = time.monotonic()
    if self._cached_graph is None or (now - self._graph_built_at) > self._graph_ttl:
        try:
            self._cached_graph = _VaultGraph(self.root_dir)  # WRITE
            self._graph_built_at = now                       # WRITE
        except Exception as e:
            logger.error("Graph build failed: %s", e)
            self._graph_built_at = now                       # WRITE
            return None
    return self._cached_graph
```

### Thread Context

1. **GPU Semaphore**: `_gpu_sem = asyncio.Semaphore(1)` (mcp_server.py:46) limits concurrent GPU calls to 1
   - All search_vault / search_codebase / search_all MCP tools acquire `_gpu_sem` before calling searcher methods (mcp_server.py:207, 255, 280)
   - Watcher also acquires `_gpu_sem` before indexing (watcher.py:129, 155)

2. **Call paths**:
   - MCP tool threads: acquire `_gpu_sem`, run sync function in thread pool via `anyio.to_thread.run_sync()`, call `VaultSearcher.search_*()` which calls `_get_graph()`
   - Watcher thread: async context, acquires `_gpu_sem` before indexing (not searching)
   - User code: could call `searcher._get_graph()` directly without acquiring `_gpu_sem`

### Is There a Race?

**Unlikely but possible:**

- `_gpu_sem` only serializes GPU operations, not all searcher calls
- If two threads both find `_cached_graph is None`, both could call `_VaultGraph(self.root_dir)` simultaneously
- Result: Double graph instantiation (~2-4s wasted), but no data corruption (both produce same graph)
- **Not a critical correctness issue**, but inefficient

**However:**

- In normal operation (MCP tools only), GPU semaphore enforces single-threaded access
- Direct user calls to `_get_graph()` without semaphore protection are out of scope for this audit (framework issue, not library bug)

### Verdict

No lock is needed for `_cached_graph` assignment because:

1. MCP is the primary interface (all calls go through `_gpu_sem`)
2. Double initialization is benign (VaultGraph is read-only after init)
3. Assignment is atomic at Python level (not a C race condition)

**BUT** documenting the threading contract would clarify this.

---

## Investigation 4: Watcher Does NOT Invalidate Graph Cache (Deeper Check)

**FINDING SEVERITY:** CRITICAL (confirmed)

### Code Trace

**watcher.py:118–142** (vault changes):

```python
if vault_changed:
    ...
    async with gpu_sem:
        result = await anyio.to_thread.run_sync(
            vault_indexer.incremental_index  # Call indexer
        )
    _last_vault_index = time.monotonic()
    # NO graph invalidation here
```

**mcp_server.py:348–378** (MCP reindex_vault tool):

```python
def _run() -> IndexResponse:
    comp = get_comp()
    ...
    if clean:
        result = comp.vault_indexer.full_index(clean=True)
    else:
        result = comp.vault_indexer.incremental_index()
    # EXPLICIT INVALIDATION:
    comp.searcher._graph_built_at = 0.0  # <-- Line 365
    return IndexResponse(...)
```

**Confirmed:** Watcher does NOT reset `_graph_built_at` after calling `incremental_index()`.

---

## Summary of Findings

| Investigation | Severity | Status | Issue |
|---|---|---|---|
| **I1: Watcher → graph cache gap** | CRITICAL | **CONFIRMED** | Watcher calls incremental_index() but does NOT invalidate_graph_built_at; searches within 300s use stale graph boost scores |
| **I2: Reranker OOM backoff** | HIGH | **CONFIRMED** | batch_size=32 hardcoded; no torch.cuda.OutOfMemoryError catch; unlike embeddings.py, no exponential backoff |
| **I3: Graph cache thread safety** | MEDIUM | **NOT AN ISSUE** | GPU semaphore serializes all MCP calls; double initialization is benign; no explicit lock needed |
| **I4: Watcher invalidation (deeper)** | CRITICAL | **CONFIRMED** | Reindex tools (mcp_server.py) set_graph_built_at=0.0 after index; watcher path does not |

---

## Recommendations

### CRITICAL (Fix immediately)

**C1: Invalidate graph cache in watcher after incremental_index()**

Add after each `incremental_index()` call in watcher.py:

- After line 131 (vault reindex): Set `comp.searcher._graph_built_at = 0.0`
- After line 157 (code reindex): Code reindex does NOT use graph, so skip

**Note:** Watcher does not have access to `comp` (RagComponents). Will need to pass searcher as parameter.

### HIGH (Fix in next iteration)

**H1: Add OOM fallback to CrossEncoder reranker**

Wrap `reranker.predict()` in try/except with exponential backoff, matching embeddings.py pattern:

- Catch `torch.cuda.OutOfMemoryError`
- Reduce batch_size by half, retry
- If batch_size reaches 1 and still OOM, re-raise
- Log warnings per retry

**H2: Make reranker batch_size configurable**

Add `reranker_batch_size` to config.py defaults (suggest 32, matching current hardcoded value). Allow override in tests.

### MEDIUM (Documentation)

**M1: Document graph cache threading contract**

Add docstring to `_get_graph()` and `VaultSearcher.__init__()` clarifying:

- GPU semaphore serializes MCP calls
- Double initialization is benign (read-only graph)
- Direct calls to `_get_graph()` should acquire semaphore if concurrent

---

## Affected Code

- **watcher.py**: Lines 118–142 (vault reindex), lines 144–168 (code reindex)
- **search.py**: Lines 239–251 (_get_graph), lines 222–237 (_rerank)
- **mcp_server.py**: Lines 365 (explicit invalidation), lines 207/255/280 (gpu_sem usage)
- **config.py**: Lines 18–29 (no reranker_batch_size config)

---

## Verification Notes

- All watcher exception handlers are correct (lines 128–142, 154–168): GPU semaphore is released even on exception
- Engine cache double-check locking in api.py is correct (per MEMORY.md Task #25)
- SearchResult dataclass is properly defined and validated across MCP serialization
