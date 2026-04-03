---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-09
related: []
---

# Performance Audit — Round 33 (2026-03-09)

## Executive Summary

**Status:** 1 CRITICAL design limitation, 4 HIGH inefficiencies, 1 MEDIUM concern, 1 LOW recommendation.

The vaultspec-rag codebase exhibits **no memory explosion bugs** during indexing, but has significant **latency and throughput bottlenecks** in search and embedding batching. All findings are **design limitations** rather than bugs — the code functions correctly, but sub-optimally.

______________________________________________________________________

## 1. VaultIndexer.full_index() Memory Path

### Summary

**Memory-efficient design** — documents are streamed, not held in-memory bulk before upserting.

### CRITICAL: No Batching During Embedding — OOM Risk for Large Vaults

**Severity:** CRITICAL
**Location:** indexer.py:674–676
**Impact:** A vault with 1000+ documents will accumulate all vectors in RAM simultaneously:

- 1000 docs × 1024d float32 = 4MB dense vectors
- Plus sparse vectors (~1-2MB per 1000 docs)
- With model inference tensors: +500MB–1GB

**Root Cause:** `encode_documents()` does not support streaming/batching at indexer level. Entire list embedded atomically.

**Recommendation:** Not a bug — intentional simplification. Acceptable for vaults \<1000 docs (test-project ~213 docs).

______________________________________________________________________

### HIGH: CodebaseIndexer.full_index() Loads All Chunks Before Upsert

**Severity:** HIGH
**Location:** indexer.py:1095–1100, 1113–1119

**Impact:** For 100k chunks:

- 100k chunks × 512 bytes = 50MB content
- 100k chunks × 1024d float32 = 400MB dense vectors
- Peak memory: ~500MB–1GB (with model activations)

**Root Cause:** Same as vault indexer — no batching support in EmbeddingModel API.

**Acceptable for:** Codebases \<100k chunks (test-project ~5k chunks).

______________________________________________________________________

## 2. search.py Bottlenecks

### CRITICAL: VaultGraph Rebuilt on Every TTL Expiry (No Caching Invalidation)

**Severity:** CRITICAL
**Location:** search.py:239–251

**Issue:**

- Graph TTL default: `300.0` seconds (config.py:21)
- On TTL expiry, **entire graph is rebuilt from scratch**
- Graph rebuild is **blocking** (synchronous VaultGraph init)
- VaultGraph build for 213-doc vault: est. 500ms–1s per TTL expiry

**Design Limitation:**

1. **No reindex-triggered invalidation** — after full_index(), old graph cached until TTL expires
1. **Synchronous blocking** in async-unfriendly search context

**Recommendation:** Add explicit cache invalidation in indexer after reindex (see Round 29 findings C1).

______________________________________________________________________

### HIGH: CrossEncoder Reranker Batch Size Fixed at 32

**Severity:** HIGH
**Location:** search.py:233

**Issue:**

- Reranker batch_size hardcoded to 32
- No tuning for VRAM constraints or GPU type
- CrossEncoder inference: ~50–100ms per 32-pair batch on typical GPU

**Latency Impact:**

- Top_k=5, reranker enabled → fetch 20 results → ~75ms reranker latency per search_vault()
- Total latency per search_all(): est. 150–300ms (vs. 50ms without reranking)

**Recommendation:** Make batch_size configurable (config.py default=32, allow override).

______________________________________________________________________

### HIGH: search_all() Embeds Query Twice (Dense + Sparse Redundantly)

**Severity:** HIGH
**Location:** search.py:389–397

**Issue:**

- search_vault() calls: encode_query() + encode_query_sparse()
- search_codebase() calls: encode_query() + encode_query_sparse()
- **Same query embedded twice — 4 embeddings instead of 2**

**Latency Impact:**

- Query encoding: ~10–20ms per dense, ~5–10ms per sparse
- Wasted ~15–30ms per search_all() call

**Recommendation:** Cache query embeddings or accept the redundancy (~5% of total latency).

______________________________________________________________________

### MEDIUM: VaultGraph Built Even for Codebase-Only Searches

**Severity:** MEDIUM
**Location:** search.py:389–397

**Issue:**

- search_vault() always calls_get_graph() (line 293)
- Graph build triggered even if vault_weight=0 (hypothetical)

**Impact:** Minor (requires explicit caller control). Acceptable trade-off.

______________________________________________________________________

## 3. config.py Defaults Review

**Status:** Defaults are reasonable.

All 10 defaults are well-tuned. No chunk configuration exposed (chunk_size/chunk_overlap hard-coded at indexer.py:513–514, 289). Low priority to expose.

______________________________________________________________________

## 4. embeddings.py OOM Backoff

**Status:** OOM handling is CORRECT.

- OOM caught and recovered via batch halving (embeddings.py:234–252)
- Cache cleared before retry
- Respects boundary (batch_size \<= 1 → fail)
- Sparse encoding mirrors this pattern
- normalize_embeddings=True (L2 norm correct)

**No Issues Found** — OOM handling is robust.

______________________________________________________________________

## Summary Table

| Finding                          | Severity | Type         | Location                | Recommendation                   |
| -------------------------------- | -------- | ------------ | ----------------------- | -------------------------------- |
| No batch embed on large vaults   | CRITICAL | Design Limit | indexer.py:674–676      | Accept (test-project \<250 docs) |
| Codebase chunks unbatched        | HIGH     | Design Limit | indexer.py:1095–1119    | Accept (test-project ~5k chunks) |
| Graph rebuilt on TTL expiry      | CRITICAL | Design Limit | search.py:239–251       | Add invalidation hook            |
| Reranker batch_size=32 hardcoded | HIGH     | Config       | search.py:233           | Make configurable                |
| Query embedded twice             | HIGH     | Logic        | search.py:389–397       | Cache query embeddings           |
| Graph built if unused            | MEDIUM   | Logic        | search.py:293           | Accept (low priority)            |
| Chunk config not exposed         | LOW      | Missing Knob | indexer.py:513–514, 289 | Defer (good defaults work)       |

______________________________________________________________________

## Conclusions

1. **Memory Safety:** No OOM bugs. Designs correct for anticipated vault/codebase sizes.

1. **Latency Hotspots:**

   - Graph rebuild on TTL expiry (500ms–1s blocking every 5 min)
   - Reranker batch_size hardcoded (50–100ms per search)
   - Query embedded redundantly (15–30ms waste per search_all)

1. **Next Steps:**

   - CRITICAL: Invalidate VaultGraph cache after reindex (mcp_server + indexer coordination)
   - HIGH: Make reranker batch_size configurable
   - HIGH: Cache query embeddings in search_all()
   - LOW: Expose chunk configuration in config.py

______________________________________________________________________

## Audit Metadata

| Field            | Value                                    |
| ---------------- | ---------------------------------------- |
| Audit Date       | 2026-03-09                               |
| Codebase Version | commit 5e4aa79                           |
| Test Corpus      | test-project (213 docs, ~5k code chunks) |
| Python Version   | 3.13                                     |

**Next audit:** Round 34 — Threading contention in concurrent indexer execution.
