---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
---

# ADR Test Coverage Audit — 2026-03-07

For each ADR: does a test exist that would **fail** if the decision were violated?

______________________________________________________________________

## 1. gpu-only-rag-stack (2026-03-06)

**Decision:** GPU-only inference with SentenceTransformer(Qwen3-Embedding-0.6B) + SparseEncoder(splade-v3). No CPU fallback. CUDA required.

**Verdict: PARTIALLY COVERED**

- `test_embeddings.py:18` asserts `model.device == "cuda"` -- would fail if CPU fallback added.
- `test_embeddings.py:25,30,61` assert `vectors.shape[1] == model.dimension` -- would catch dimension change.
- **GAP:** No test asserts the model name is `Qwen/Qwen3-Embedding-0.6B`. Swapping to a different model (e.g. nomic) with the same dimension would not be caught.
- **GAP:** No test asserts the sparse model is `naver/splade-v3`. Swapping sparse models would not be caught.
- **GAP:** No test asserts `torch_dtype=float16` or `flash_attention_2`. Inference precision could silently change.

______________________________________________________________________

## 2. rag-stack-migration (2026-03-06)

**Decision:** Superseded by gpu-only-rag-stack. Not independently testable.

**Verdict: N/A (SUPERSEDED)**

______________________________________________________________________

## 3. blake2b-file-hashing (2026-03-07)

**Decision:** Use `hashlib.blake2b` via `hashlib.file_digest()` for file change detection.

**Verdict: GAP**

- `test_indexer_unit.py:310,392,466,730` all use `hashlib.sha256` to compute expected hashes, confirming the code currently uses SHA-256, **not blake2b as the ADR requires**.
- No test asserts the hashing algorithm is blake2b. If someone changed sha256 to md5, the unit tests would still pass (they recompute with whichever algorithm the code uses).
- The ADR itself is NOT IMPLEMENTED (code uses sha256), so there is nothing to regress against. This is an implementation gap, not a test gap.

______________________________________________________________________

## 4. manual-node-walking (2026-03-07)

**Decision:** Use `node.child_by_field_name("name")` for metadata extraction, not Query API.

**Verdict: COVERED**

- `test_indexer_unit.py:557-615` — TestMetadataExtraction tests function_name and class_name extraction for Python and Rust. These test the **output** of metadata extraction (correct names extracted from real tree-sitter parses).
- `test_indexer_unit.py:619-629` — TestCodeChunkMetadata tests `_chunk_with_ast` populates function_name.
- `test_indexer_unit.py:870-889` — Tests non-ASCII identifier extraction via ASTChunker.
- If `child_by_field_name` were replaced with Query API, these tests would still pass (they test behavior, not implementation). But if metadata extraction **broke**, these would catch it. This is the correct kind of coverage.

______________________________________________________________________

## 5. mcp-sync-tools (2026-03-07)

**Decision:** MCP tools should be plain `def`, not `async def`. SDK auto-wraps in `anyio.to_thread.run_sync()`.

**Verdict: GAP**

- No test inspects whether MCP tool functions are `def` vs `async def`.
- No test verifies the event loop stays responsive during tool execution.
- Per the ADR compliance audit, this ADR is **CONTRADICTED** -- tools are still `async def` with manual `asyncio.to_thread()`. A test asserting sync would catch this.

______________________________________________________________________

## 6. path-resolve-engine-cache (2026-03-07)

**Decision:** Use `Path.resolve()` to normalize vault paths before engine cache lookup.

**Verdict: GAP**

- `test_api_integration.py:154-161` tests engine singleton (same root returns same instance), but uses the **same Path object** both times. Does not test equivalent paths like `Path("./project")` vs `Path("project")`.
- No test passes two lexically-different-but-equivalent paths and asserts they return the same engine.
- Per the ADR compliance audit, this ADR is **NOT IMPLEMENTED** (api.py:53 uses lexical comparison).

______________________________________________________________________

## 7. qdrant-filter-on-prefetch (2026-03-07)

**Decision:** Filters must go on each Prefetch individually, not top-level `query_filter`.

**Verdict: PARTIALLY COVERED**

- `test_quality.py:136-144` asserts `type:adr` filter returns ONLY adr docs. If filters were silently ignored (top-level only), this would return non-adr docs and fail.
- `test_quality.py:195-207` tests two-filter intersection (`type:adr feature:editor-demo`).
- `test_search_integration.py:49-57,130-138,154` tests filtered search returns correct doc_types.
- **These tests cover the behavior** (filters work correctly). If someone moved filters from Prefetch to top-level `query_filter`, these tests would fail because Qdrant ignores top-level filters with Prefetch.
- **GAP:** No unit test inspects the Qdrant API call structure to verify filters are on Prefetch objects specifically. Only behavioral integration tests cover this.

______________________________________________________________________

## 8. qdrant-payload-indexes-local (2026-03-07)

**Decision:** Call `create_payload_index()` at setup time for forward compatibility.

**Verdict: GAP**

- No test verifies that `create_payload_index()` is called during collection setup.
- No test checks which payload fields are indexed.
- Since indexes are no-ops in local mode, removing the calls would have zero observable behavioral effect -- no test could catch this without inspecting the API calls.
- Per ADR compliance audit: PARTIALLY IMPLEMENTED (missing `line_start`, `date`, `tags` indexes).

______________________________________________________________________

## 9. qwen3-no-document-prompt (2026-03-07)

**Decision:** Documents encoded without prompt; queries use `prompt_name="query"`.

**Verdict: GAP**

- No test asserts that `encode_documents()` does NOT pass `prompt_name`.
- No test asserts that `encode_query()` passes `prompt_name="query"`.
- If someone added `prompt_name="document"` to `encode_documents`, no test would fail (the document prompt is empty string, so it's functionally identical). But if they removed `prompt_name="query"` from `encode_query`, retrieval quality would degrade 1-5% -- no test has tight enough precision thresholds to catch this.

______________________________________________________________________

## 10. score-normalization (2026-03-07)

**Decision:** Sigmoid + min-max normalization in `search_all()` before combining vault and code results.

**Verdict: GAP**

- `test_search_integration.py:93-104` tests `search_all` returns results, but only on a vault-only index (no code), so no cross-source score mixing occurs.
- No test verifies scores are normalized before combining.
- No test verifies `_sigmoid()` or `_min_max()` helpers exist or produce correct output.
- Per ADR compliance audit: NOT IMPLEMENTED (raw concatenation, no normalization).

______________________________________________________________________

## 11. threading-lock-for-singleton (2026-03-07)

**Decision:** Use `threading.Lock` with double-checked locking for `get_comp()`.

**Verdict: PARTIALLY COVERED**

- `test_mcp_server.py:266-272` asserts `mod._comp_lock` is a `threading.Lock` instance.
- `test_mcp_server.py:246-264` tests that cached errors raise immediately on retry.
- **GAP:** No test exercises **concurrent** access to `get_comp()` (e.g., two threads racing). The lock is verified to exist but never stressed.

______________________________________________________________________

## 12. vaultgraph-cache (2026-03-07)

**Decision:** Cache VaultGraph with `threading.Lock` and explicit invalidation after reindex.

**Verdict: GAP**

- `test_performance.py:146-147` has `test_graph_cache_reused_across_searches` and `test_graph_cache_ttl_expiry` -- these test graph caching at the searcher level.
- **GAP:** No test verifies `_graph_cache` in `api.py` exists or caches correctly. Per ADR compliance audit, this is NOT IMPLEMENTED -- `api.py` rebuilds VaultGraph on every `get_related()` call.
- No test verifies `invalidate()` is called after reindex.

______________________________________________________________________

## Summary

| #   | ADR                          | Verdict | Key Gap                                                                                 |
| --- | ---------------------------- | ------- | --------------------------------------------------------------------------------------- |
| 1   | gpu-only-rag-stack           | PARTIAL | No assertion on model names, dtype, or attention impl                                   |
| 2   | rag-stack-migration          | N/A     | Superseded                                                                              |
| 3   | blake2b-file-hashing         | GAP     | ADR not implemented (sha256 used). Tests use sha256 too. No algorithm assertion.        |
| 4   | manual-node-walking          | COVERED | Behavioral tests verify metadata extraction works                                       |
| 5   | mcp-sync-tools               | GAP     | No test checks sync vs async. ADR contradicted (still async).                           |
| 6   | path-resolve-engine-cache    | GAP     | No test with equivalent-but-different paths. ADR not implemented.                       |
| 7   | qdrant-filter-on-prefetch    | PARTIAL | Behavioral tests would catch breakage. No structural test of Prefetch filter placement. |
| 8   | qdrant-payload-indexes-local | GAP     | No-op in local mode, untestable without API inspection. Partial impl.                   |
| 9   | qwen3-no-document-prompt     | GAP     | No assertion on prompt_name presence/absence                                            |
| 10  | score-normalization          | GAP     | ADR not implemented. No normalization tests.                                            |
| 11  | threading-lock-for-singleton | PARTIAL | Lock exists but no concurrency stress test                                              |
| 12  | vaultgraph-cache             | GAP     | ADR not implemented. No cache tests in api.py.                                          |

**Result: 1 COVERED, 3 PARTIAL, 7 GAP, 1 N/A.**

Seven ADR decisions have no test that would catch a regression. Four of those (blake2b, path-resolve, score-normalization, vaultgraph-cache) are also not implemented, meaning the gap is compounded: both the implementation and the safety net are missing.
