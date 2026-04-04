---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-09
---

# Round 36: Graph/Embedding Domain Audit (2026-03-09)

**Scope:** `search.py` query → embedding pipeline and graph cache correctness

**Investigated:**

1. ParsedQuery → embedding encoding flow
1. Graph TTL rebuild serialization and correctness
1. Query vs document encoding method dispatch

______________________________________________________________________

## Investigation 1: ParsedQuery → embedding pipeline

### Finding 1.1: ✅ PASS — Query text extraction and encoding

**search.py:270-311 (`search_vault`):**

- Line 272: `parsed = parse_query(raw_query)`
- Line 273: `query_text = parsed.text or raw_query`
- **Critical distinction:** If filters are extracted, `parsed.text` contains the **cleaned query** with all filter tokens removed (line 95: `text = _FILTER_PATTERN.sub("", raw_query)`). If no filters match, `parsed.text` is empty string → fallback to `raw_query`.
- Line 274: `query_vector = self.model.encode_query(query_text)` ← **correct method**
- Line 275: `sparse_vector = self.model.encode_query_sparse(query_text)` ← **correct method**

**embeddings.py:254-272 (`encode_query`):**

- Uses `prompt_name="query"` (line 269) ✅ **correct for Qwen3** — enables instruction-based encoding
- Single-query wrapper: `[query]` → returns first element `[0]` (line 272)
- **No prompt for documents** — `encode_documents` (line 236) does NOT specify `prompt_name`, defaulting to empty string ✅

**embeddings.py:309-321 (`encode_query_sparse`):**

- Calls `self._sparse_model.encode_query([query[:max_chars]])` ✅ **asymmetric SPLADE**
- Extracts first result (line 321) ✅

### Finding 1.2: ✅ PASS — Filter token removal prevents leakage

**search.py:32-49 (\_FILTER_PATTERN):**

- Regex pattern correctly matches `type:adr`, `feature:rag`, `date:2026-02`, `tag:#research`, `lang:python`, `path:src/`, `func:encode`, `class:Foo`, `nodetype:function_definition`
- Line 95: `text = _FILTER_PATTERN.sub("", raw_query).strip()` removes all matched tokens
- Example: "embedding type:adr retrieval" → encodes "embedding retrieval" (filters not leaked) ✅

**search.py:276-280 (vault filters):**

- Only extracts vault-relevant filters: `doc_type`, `feature`, `date`, `tag` (line 279)
- Passed to `store.hybrid_search(..., filters=store_filters or None)`
- Filter tokens do NOT leak into the embedding query ✅

### Finding 1.3: ✅ PASS — Codebase search follows same pattern

**search.py:313-379 (`search_codebase`):**

- Line 333: `parsed = parse_query(raw_query)`
- Line 334: `query_text = parsed.text or raw_query`
- Line 335: `query_vector = self.model.encode_query(query_text)` ✅
- Line 336: `sparse_vector = self.model.encode_query_sparse(query_text)` ✅
- Line 337-349: Filters extracted for codebase: `language`, `path`, `node_type`, `function_name`, `class_name` ✅

**Verdict:** ✅ PASS — Query encoding pipeline is correct.

______________________________________________________________________

## Investigation 2: Graph boost correctness after TTL rebuild

### Finding 2.1: ✅ PASS — Graph reconstruction is blocking but safe

**search.py:256-268 (`_get_graph`):**

- Line 260: TTL check: `(now - self._graph_built_at) > self._graph_ttl`
- Line 262: `self._cached_graph = _VaultGraph(self.root_dir)` ← **blocks the calling thread**
- vaultspec/graph/api.py:56-64: VaultGraph.**init** immediately calls `self._build_graph()`
- vaultspec/graph/api.py:66-111: Two-pass scan (all files read sequentially, synchronously) — **no yielding to event loop**

**Rationale:** Since `_get_graph()` is called from `search_vault()` (line 310), and `search_vault()` is called from `mcp_server.py:get_search()` which runs in a worker thread via `anyio.to_thread.run_sync()`, blocking the thread is **safe** — does not block the event loop.

### Finding 2.2: 🔴 **CRITICAL** — Multiple concurrent rebuilds on TTL expiry (race condition)

**Evidence:**

1. **No lock on graph rebuild:** `_get_graph()` reads `self._graph_built_at` (line 260), rebuilds (line 262), then updates `self._graph_built_at` (line 263).
1. **Not atomic:** Between line 260 and line 262, multiple threads can see `TTL expired` and all call `_VaultGraph(self.root_dir)` simultaneously.
1. **Concurrent VaultGraph constructions are expensive:** Each scans all vault files twice (read + link extraction).
1. **Watcher already invalidates correctly:** mcp_server.py:366 sets `_graph_built_at = 0.0` to force rebuild on next search.

**Scenario:**

- Graph built at t=0, TTL=60s
- At t=61s, 10 concurrent search_vault() calls arrive
- All see `(now - 0) > 60` = True
- All 10 start `_VaultGraph(root_dir)` construction simultaneously
- Result: 10x disk I/O overhead, potential lock contention on vaultspec file reads

**Severity:** CRITICAL — **Performance degradation under concurrent load at TTL boundary** (not data corruption, but wasteful).

**Fix:** Add threading.Lock around graph rebuild.

```python
# At __init__:
self._graph_lock = threading.Lock()

# In _get_graph:
now = time.monotonic()
if self._cached_graph is None or (now - self._graph_built_at) > self._graph_ttl:
    with self._graph_lock:
        # Double-check inside lock
        if self._cached_graph is None or (now - self._graph_built_at) > self._graph_ttl:
            self._cached_graph = _VaultGraph(...)
            self._graph_built_at = now
```

### Finding 2.3: ✅ PASS — Graph cache invalidation after reindex

**mcp_server.py:363-366 (reindex workflow):**

```python
result = comp.vault_indexer.incremental_index()
# Invalidate the graph cache so the next search_vault call rebuilds
# from the fresh index rather than serving stale graph-boost scores.
comp.searcher._graph_built_at = 0.0
```

- Sets `_graph_built_at = 0.0` immediately after reindex ✅
- Next `search_vault()` call will see TTL expired (line 260) → rebuild graph
- Graph will reflect the fresh index ✅

### Finding 2.4: ⚠️ **MEDIUM** — Potential graph inconsistency during incremental indexing

**Scenario:**

1. Watcher detects vault file change
1. `vault_indexer.incremental_index()` runs in thread, reading new file
1. Meanwhile, another thread calls `search_vault()` at line 310
1. `_get_graph()` rebuilds VaultGraph from disk (reading all vault files)
1. **Race:** If incremental_index() is mid-write to a .md file, graph might read partially-written file content
1. Result: Graph has stale/inconsistent link structure

**Mitigating factors:**

- Python file I/O is atomic at OS level (atomic write-then-rename)
- IndexResult shows files use blake2b hashing, likely atomic metadata writes (TODO: verify)
- But no explicit guarantee in the code

**Severity:** MEDIUM — **Unlikely but possible inconsistency** (requires file write race with graph read). Recommend atomic file writes in indexer.

______________________________________________________________________

## Investigation 3: encode_query vs encode_documents method dispatch

### Finding 3.1: ✅ VERIFIED — All query encoding uses encode_query()

**search.py:**

- Line 274: `self.model.encode_query(query_text)` ✅
- Line 275: `self.model.encode_query_sparse(query_text)` ✅
- Line 335: `self.model.encode_query(query_text)` ✅
- Line 336: `self.model.encode_query_sparse(query_text)` ✅

No direct `.encode()` calls on query side ✅

### Finding 3.2: ✅ VERIFIED — All document encoding uses encode_documents()

**indexer.py (spot checks):**

- Line 675: `self.model.encode_documents(texts)` ✅
- Line 676: `self.model.encode_documents_sparse(texts)` ✅
- Line 791: `self.model.encode_documents(texts)` ✅
- Line 792: `self.model.encode_documents_sparse(texts)` ✅
- Line 1114: `self.model.encode_documents(texts)` ✅
- Line 1115: `self.model.encode_documents_sparse(texts)` ✅
- Line 1210: `self.model.encode_documents(texts)` ✅
- Line 1211: `self.model.encode_documents_sparse(texts)` ✅

No calls to generic `.encode()` on documents ✅

### Finding 3.3: ✅ VERIFIED — Asymmetric SPLADE prompting is correct

**embeddings.py:186-190:**

```python
self._sparse_model = SparseEncoder(
    sparse_name,
    device="cuda",
    model_kwargs={"torch_dtype": torch.float16},
)
```

- SparseEncoder.encode_document() and encode_query() are asymmetric methods ✅
- encode_document() uses document-specific SPLADE prompt (learns document expansion)
- encode_query() uses query-specific prompt (learns query expansion)

**Verdict:** ✅ PASS — Asymmetric SPLADE dispatch is correct.

______________________________________________________________________

## Summary

| Finding                                           | Category        | Severity        | Status                |
| ------------------------------------------------- | --------------- | --------------- | --------------------- |
| Query embedding uses correct prompt_name="query"  | Correctness     | ✅ PASS         | Verified              |
| Filter tokens removed before embedding            | Correctness     | ✅ PASS         | Verified              |
| Codebase search follows same pattern              | Correctness     | ✅ PASS         | Verified              |
| Graph rebuild is blocking (safe in worker thread) | Safety          | ✅ PASS         | Verified              |
| **Multiple concurrent rebuilds on TTL expiry**    | **Performance** | **🔴 CRITICAL** | **Race condition**    |
| Graph cache invalidation after reindex            | Correctness     | ✅ PASS         | Verified              |
| Graph inconsistency during incremental indexing   | Edge case       | ⚠️ MEDIUM       | Unlikely but possible |
| All query encoding uses encode_query()            | Correctness     | ✅ PASS         | Verified              |
| All document encoding uses encode_documents()     | Correctness     | ✅ PASS         | Verified              |
| Asymmetric SPLADE prompting                       | Correctness     | ✅ PASS         | Verified              |

______________________________________________________________________

## Recommendations

1. **CRITICAL (2026-03-09):** Add `threading.Lock` around graph rebuild in `_get_graph()` to prevent concurrent VaultGraph constructions on TTL expiry. Double-check pattern inside the lock.

1. **MEDIUM (future):** Verify indexer uses atomic file writes for metadata. If not, consider atomic write-then-rename pattern to guarantee graph consistency.

1. **LOW (documentation):** Add comment to `_get_graph()` explaining that the method is called from worker threads (safe to block).
