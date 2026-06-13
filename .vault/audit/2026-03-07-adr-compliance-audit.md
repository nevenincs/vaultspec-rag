---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
---

# ADR Compliance Audit -- 2026-03-07

## mcp-sync-tools

Status: **CONTRADICTED**
Evidence: `mcp_server.py:136` `async def search_vault`, `:158` `async def search_codebase`, `:198` `async def search_all`, `:246` `async def reindex_vault`, `:275` `async def reindex_codebase`. All 5 tools are `async def` with manual `asyncio.to_thread()` calls inside. Only `get_index_status` (`:214`) and `get_code_file` (`:225`) are sync `def`.
Gap: ADR says "Declare all MCP tool functions as plain `def` (synchronous), not `async def`" and "Remove `async` and `await` keywords from all `@mcp.tool()` functions." Code does the opposite -- uses `async def` with manual `asyncio.to_thread()` instead of letting the SDK auto-wrap sync functions via `anyio.to_thread.run_sync()`. The ADR also notes `anyio.to_thread.run_sync()` is correct (not `asyncio.to_thread()`), so the manual wrapping uses the wrong threading API.

## threading-lock-for-singleton

Status: **IMPLEMENTED**
Evidence: `mcp_server.py:43` `_comp_lock = threading.Lock()`, `:47-83` `get_comp()` uses double-checked locking pattern. Fast path at `:54` `if _comp is not None: return _comp`, lock acquisition at `:56` `with _comp_lock:`, inner check at `:58` `if _comp is not None: return _comp`, error caching at `:60-63` and `:80-82`.
Gap: None. The ADR's code example uses `_components` as the variable name while the code uses `_comp` -- trivial naming difference, pattern is identical.

## qdrant-filter-on-prefetch

Status: **IMPLEMENTED**
Evidence: `store.py:540-545` dense prefetch has `filter=query_filter`. `:549-558` sparse prefetch has `filter=query_filter`. Same pattern in `hybrid_search_codebase` at `:609-628`. No top-level `query_filter` is passed to `query_points()` when using prefetch+FusionQuery.
Gap: None.

## blake2b-file-hashing

Status: **NOT YET IMPLEMENTED**
Evidence: `indexer.py:10` `import hashlib`. `:752` `current_hashes[doc_id] = hashlib.sha256(path.read_bytes()).hexdigest()`. `:821` `hashlib.sha256(path.read_bytes()).hexdigest()`. `:1050` `hashlib.sha256(p.read_bytes()).hexdigest()`. `:1123` `hashlib.sha256(...)`. All 4 hashing sites use `hashlib.sha256` with `path.read_bytes()`.
Gap: ADR says use `hashlib.blake2b` via `hashlib.file_digest()` (Python 3.11+). Code uses `sha256` with `read_bytes()` (reads entire file into memory) instead of streaming `file_digest()`. Two issues: (1) wrong algorithm (sha256, not blake2b -- 3x slower), (2) wrong API (`read_bytes()` loads entire file into memory vs `file_digest()` which streams in chunks). For the 213-doc vault this is inconsequential, but the ADR decision was explicitly to use blake2b + file_digest.

## score-normalization

Status: **NOT YET IMPLEMENTED**
Evidence: `search.py:343-350` `search_all()`:

```python
vault_results = self.search_vault(raw_query, top_k=top_k)
code_results = self.search_codebase(raw_query, top_k=top_k)
all_results = vault_results + code_results
all_results.sort(key=lambda r: r.score, reverse=True)
return all_results[:top_k]
```

Gap: ADR says to apply sigmoid normalization to CrossEncoder logits, min-max normalization to RRF scores, then combine with configurable weights. Code does raw concatenation and sort by raw score with no normalization whatsoever. No `_sigmoid()` or `_min_max()` helper functions exist anywhere in `search.py`. This is the exact problem the ADR was created to solve (R21-M1: `search_all` mixes incomparable scores).

## path-resolve-engine-cache

Status: **NOT YET IMPLEMENTED**
Evidence: `api.py:53` `if _engine is None or _engine.root_dir != root_dir:`. The comparison is raw `Path` equality (lexical), not resolved. `_Engine.__init__` at `:38-39` stores `self.root_dir = root_dir` without calling `.resolve()`.
Gap: ADR says `Path.resolve()` must be used to normalize vault paths before cache comparison. Code uses lexical Path comparison. This means `Path("./project")` and `Path("project")` would create separate engines pointing to the same data, wasting GPU memory (the exact bug the ADR describes).

## vaultgraph-cache

Status: **NOT YET IMPLEMENTED**
Evidence: `api.py:163-166`:

```python
from vaultspec.graph import VaultGraph
try:
    graph = VaultGraph(root_dir)
```

`get_related()` constructs a fresh `VaultGraph` on every invocation. No `_GraphCache` class, no `threading.Lock`, no caching, no invalidation.
Gap: ADR specifies a `_GraphCache` class with `threading.Lock`, double-checked locking for construction, and `invalidate()` after reindex. None of this exists. Every `get_related()` call re-reads all vault files from disk twice (metadata + links pass).

## qwen3-no-document-prompt

Status: **IMPLEMENTED**
Evidence: `embeddings.py:236-241` `encode_documents` calls `self._dense_model.encode(truncated, ...)` without `prompt_name`. `embeddings.py:267-269` `encode_query` calls `self._dense_model.encode([query], prompt_name="query", ...)`. Matches the ADR: queries get `prompt_name="query"`, documents get no prompt.
Gap: None.

## manual-node-walking

Status: **IMPLEMENTED**
Evidence: `indexer.py:333` `name_node = node.child_by_field_name("name")` for name extraction. `:342-375` `_unwrap_decorated` handles `decorated_definition` by calling `node.child_by_field_name("definition")` to get the inner node, then extracting name from the real definition. `:366-375` checks if inner child type is in `_CLASS_LIKE_NODES` or `_FUNCTION_LIKE_NODES` to correctly classify decorated classes vs functions. No tree-sitter Query API used anywhere.
Gap: None.

## qdrant-payload-indexes-local

Status: **PARTIAL**
Evidence: `store.py:198-203` vault collection creates KEYWORD indexes on `doc_type` and `feature`. `:219-224` code collection creates KEYWORD indexes on `path`, `language`, `function_name`, `class_name`. Both use `create_payload_index()` unconditionally after `create_collection()`, which is the ADR's recommendation.
Gap: ADR recommends `line_start` INTEGER index with `range=True` for range queries. This is not created (`:219-224` only lists 4 KEYWORD fields). Also, ADR recommends vault indexes on `date` and `tags` fields (used in `_build_filter` at `:657-669`), but only `doc_type` and `feature` are indexed (`:198-203`). While these are no-ops in local mode, the forward-compatibility argument applies equally to the missing fields.

______________________________________________________________________

## Summary

| ADR                          | Status              | Action Required                                             |
| ---------------------------- | ------------------- | ----------------------------------------------------------- |
| mcp-sync-tools               | **CONTRADICTED**    | Convert 5 async tools to sync def, remove asyncio.to_thread |
| threading-lock-for-singleton | IMPLEMENTED         | None                                                        |
| qdrant-filter-on-prefetch    | IMPLEMENTED         | None                                                        |
| blake2b-file-hashing         | **NOT IMPLEMENTED** | Replace sha256 with blake2b, use file_digest()              |
| score-normalization          | **NOT IMPLEMENTED** | Add sigmoid/min-max normalization to search_all()           |
| path-resolve-engine-cache    | **NOT IMPLEMENTED** | Add .resolve() to get_engine() path comparison              |
| vaultgraph-cache             | **NOT IMPLEMENTED** | Add \_GraphCache class with threading.Lock to api.py        |
| qwen3-no-document-prompt     | IMPLEMENTED         | None                                                        |
| manual-node-walking          | IMPLEMENTED         | None                                                        |
| qdrant-payload-indexes-local | **PARTIAL**         | Add line_start INTEGER, date KEYWORD, tags KEYWORD indexes  |

**Compliance: 4/10 fully implemented, 1/10 partial, 4/10 not implemented, 1/10 contradicted.**
