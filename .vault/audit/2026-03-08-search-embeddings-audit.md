---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-08
related: []
---

# Audit Round 2: search.py & embeddings.py

**Date:** 2026-03-08
**Auditor:** docs-researcher
**Scope:** Core retrieval pipeline — query parsing, hybrid search, reranking, sparse embeddings

---

## search.py Audit

### 1. Query Filter Parsing — `parse_query()`

**Status:** PASS ✓

**Findings:**

- **Malformed filters (empty value):** Regex pattern `r"\b(type|feature|...):(\S+)"` requires non-whitespace after colon. Filters like `type:` (space) or `type:` (EOL) are correctly **not matched** — they remain in the output text.
  - Test: `"type: vector"` → matched as `type:` (no match) + text stays as `"type: vector"`
  - Test: `"type:adr extra:unknown"` → matches only `type:adr`, `extra:unknown` ignored (correct — unknown filters pass through text)
- **Unknown filter keys:** Correctly passed through to output text (e.g., `extra:value` → not extracted).
- **Test coverage:** Good — 13 tests for parse_query edge cases, including empty query, only-filters, multiple filters, tag hash stripping, space collapsing.
- **Missing:** No explicit tests for `type:` (empty value) or `type:` (space) edge cases — but behavior is safe (not matched).

**Severity:** LOW (regex design is sound; no crashes on malformed input)

---

### 2. Score Normalization — `_normalize_minmax()`

**Status:** PASS with DESIGN NOTE ⚠

**Findings:**

- **Edge case: empty result list:** Correctly returns early (line 156–157).
- **Edge case: single result:** `span = hi - lo = 0` → sets score to weight. ✓
- **Edge case: all same scores:** `span = 0` → all set to weight. ✓
- **Normal case:** Formula `(score - lo) / span * weight` correctly scales to `[0, weight]`.
- **Design note (MEDIUM):** When `search_all()` normalizes vault and code results **separately** with equal weights (default 0.5 each):
  - Vault results are scaled to [0, 0.5]
  - Code results are scaled to [0, 0.5]
  - After merge + sort, the **relative rank within each group is preserved**, but the top vault and top code result **both cap at 0.5**.
  - This creates **parity regardless of quality difference** between sources.
  - Example: vault top=0.95 (scales to 0.5), code top=0.72 (scales to 0.5) → after merge, sorted order can flip arbitrarily based on reranker logits.
  - This is **intentional** (equal weighting), but not obvious from code comments. Consider documenting.

**Severity:** MEDIUM (design intention unclear; behavior is correct but may surprise users)

---

### 3. CrossEncoder Reranking — `_rerank()`

**Status:** PASS ✓

**Findings:**

- **Input format (line 232):** Correctly constructs `(query, snippet)` tuples for `CrossEncoder.predict()`.
  - Query is raw string ✓
  - Snippet is `r.snippet` (pre-truncated to 200 chars, stripped) ✓
- **Empty snippet handling:** If `r.snippet` is `""` (empty after truncation), CrossEncoder receives empty string. SentenceTransformers will pad/tokenize it (no crash). Reranking still produces a score.
- **Batch size:** Fixed at 32 (line 233). This is GPU-safe for the BAAI/bge-reranker-v2-m3 model (lightweight reranker).
- **Score assignment (line 234–235):** Scores from CrossEncoder are cast to float and assigned back. ✓
- **Re-sort (line 236):** Results re-sorted by new scores. ✓
- **Top-k truncation (line 237):** Correctly returns `results[:top_k]`.

**Edge case:** If `len(results) <= 1`, reranking is skipped (line 229–230). ✓

**Severity:** NONE (implementation is correct)

---

### 4. Hybrid Search Score Merging — `search_all()`

**Status:** PASS ⚠

**Findings:**

- **Flow (lines 364–392):**
  1. Call `search_vault()` → returns already-reranked results with new CrossEncoder scores (if enabled).
  2. Call `search_codebase()` → returns already-reranked results with new CrossEncoder scores (if enabled).
  3. Normalize vault results separately (min-max scaling with vault_weight).
  4. Normalize code results separately (min-max scaling with code_weight).
  5. Concatenate and re-sort.
- **Issue (MEDIUM):** If vault returns 5 results and code returns 0 (or vice versa), the normalization still scales the non-empty list. The empty list is untouched. After merge, only one source appears. **This is correct**, but combining with graph reranking (below) can be confusing.
- **Graph reranking not applied:** Line 294 applies `rerank_with_graph()` only in `search_vault()`, not in `search_all()`. The `search_all()` results are **never graph-reranked**. This is intentional (graph only applies to vault docs), but the docstring for `search_all()` does not mention this.

**Severity:** MEDIUM (graph reranking is not applied; docstring should clarify)

---

### 5. Graph Reranking — `rerank_with_graph()`

**Status:** PASS ✓

**Findings:**

- **Import (lines 117–120):** Imports `VaultGraph` on-demand, with error handling.
- **Logic (lines 125–143):**
  - Only reranks vault results (correctly separates vault vs. code).
  - In-link count boost: `score *= 1 + 0.1 * min(in_link_count, 10)` → max boost is 2.0x (when in_link_count >= 10).
  - Feature filter neighbor boost: `score *= 1.15` (15% boost if neighbor has matching feature tag).
- **Re-sort (line 146–147):** After applying boosts, results are concatenated and re-sorted.
- **Function is exported (line 29):** Listed in `__all__`.
- **Edge case:** If graph build fails (exception caught, line 122), returns original results. ✓

**Severity:** NONE (implementation is correct)

---

### 6. Thread Safety — `VaultSearcher`

**Status:** PASS ✓

**Findings:**

- **Mutable state (lines 189–193):**
  - `_cached_graph`: Cached VaultGraph object. TTL-based refresh.
  - `_graph_built_at`: Last build time (float).
  - `_reranker`: Lazily-loaded CrossEncoder model.
- **Concurrent `search()` calls:**
  - Graph cache is guarded by TTL + time.monotonic() check (lines 242–250). Multiple threads may race on TTL comparison, but the worst case is redundant graph rebuild (safe).
  - Reranker is lazily-loaded once (line 201–202) and shared. CrossEncoder itself is thread-safe (SentenceTransformers uses internal locks).
- **No issues detected.**

**Severity:** NONE (thread-safe design)

---

## embeddings.py Audit

### 1. OOM Retry Logic

**Status:** PASS ✓

**Findings:**

- **`encode_documents()` (lines 234–252):**
  - Retry loop with batch_size halving on `torch.cuda.OutOfMemoryError` (lines 243–252).
  - Minimum batch_size check (line 245): `if batch_size <= 1: raise` — **raises** instead of infinite loop. ✓
  - Batch_size is halved with `batch_size = max(1, batch_size // 2)` (line 247). This ensures batch_size stays >= 1.
  - Will eventually raise on OOM with batch_size=1 if truly OOM (correct — user gets clear error).

- **`encode_documents_sparse()` (lines 291–307):**
  - Identical retry logic with same safety check. ✓

**Severity:** NONE (OOM handling is correct)

---

### 2. Sparse Embedding Return Type — `encode_documents_sparse()`

**Status:** PASS ✓

**Findings:**

- **Return type (line 276):** `list[SparseResult]` (dataclass with `.indices` and `.values`).
- **Conversion (line 297):** Calls `_sparse_tensor_to_results(sparse_tensor)` which converts SPLADE output to `list[SparseResult]`.
- **Caller usage in indexer.py (line 676, 792, 1096, 1192):**

  ```python
  sparse_vecs = self.model.encode_documents_sparse(texts)
  for doc, vec, svec in zip(docs, vectors, sparse_vecs, strict=True):
      doc.sparse_indices = list(svec.indices)  # ✓
      doc.sparse_values = list(svec.values)    # ✓
  ```

  Correctly accesses `.indices` and `.values`. ✓

**Severity:** NONE (correct usage)

---

### 3. CrossEncoder Initialization — `activation_fn`

**Status:** PASS ✓

**Findings:**

- **Line 210–214 (in `_get_reranker()`):**

  ```python
  self._reranker = CrossEncoder(
      self._reranker_model_name,
      device="cuda",
      activation_fn=torch.nn.Sigmoid(),  # ✓ CORRECT
  )
  ```

  - `activation_fn=torch.nn.Sigmoid()` is passed correctly.
  - This applies sigmoid to logits before returning scores. ✓
  - Matches CLAUDE.md requirement: "activation_fn=torch.nn.Sigmoid()".

**Severity:** NONE (correct)

---

### 4. CUDA Device Check

**Status:** PASS ✓

**Findings:**

- **`_check_rag_deps()` (lines 34–49):**
  - Line 39: `if not torch.cuda.is_available()` → raises `RuntimeError` with clear message. ✓
  - Message: "CUDA GPU required. No CUDA device found."
- **`__init__()` (line 153):** Calls `_check_rag_deps()` at construction. ✓

**Severity:** NONE (GPU check is correct)

---

### 5. Query Sparse Encoding Return Type — `encode_query_sparse()`

**Status:** PASS ✓

**Findings:**

- **Return type (line 309):** `SparseResult` (single result, not list).
- **Implementation (lines 318–321):**

  ```python
  sparse_tensor = self._sparse_model.encode_query([query[:max_chars]])
  results = _sparse_tensor_to_results(sparse_tensor)
  return results[0]  # ✓ Extract first element
  ```

- **Caller usage in search.py (lines 258, 319):**

  ```python
  sparse_vector = self.model.encode_query_sparse(query_text)
  # ...
  raw_results = self.store.hybrid_search(
      # ...
      sparse_vector=sparse_vector,  # ✓ Passes SparseResult
  )
  ```

- **Store usage in store.py (lines 571–574):**

  ```python
  query=models.SparseVector(
      indices=list(sparse_vector.indices),  # ✓
      values=list(sparse_vector.values),    # ✓
  ),
  ```

  Correctly accesses `.indices` and `.values`. ✓

**Severity:** NONE (correct usage)

---

## Integration Correctness

### store.hybrid_search() & store.hybrid_search_codebase()

**Status:** PASS ✓

**Findings:**

- **Sparse vector format (store.py lines 571–574, 641–644):**
  - Both methods construct `models.SparseVector(indices=..., values=...)` from `sparse_vector.indices` and `sparse_vector.values`.
  - Matches the `SparseResult` dataclass interface exactly. ✓
- **Prefetch construction (lines 559–566, 630–636):**
  - Dense prefetch uses raw query vector (list of floats). ✓
  - Sparse prefetch uses `models.SparseVector` from SparseResult. ✓
- **RRF merging (line 585, 655):** Uses `models.RrfQuery(rrf=models.Rrf(k=60))` with fixed k=60 (from MEMORY.md, Qdrant RRF default).

**Severity:** NONE (integration is correct)

---

## Summary Table

| Component | Status | Severity | Issue |
|-----------|--------|----------|-------|
| `parse_query()` | ✓ PASS | LOW | No tests for empty filter values (e.g., `type:`), but behavior is safe |
| `_normalize_minmax()` | ✓ PASS | MEDIUM | Separate normalization creates parity between sources; docstring could clarify intent |
| `_rerank()` | ✓ PASS | NONE | — |
| `search_all()` | ✓ PASS | MEDIUM | Graph reranking not applied; docstring should clarify |
| `rerank_with_graph()` | ✓ PASS | NONE | — |
| Thread safety | ✓ PASS | NONE | — |
| OOM retry | ✓ PASS | NONE | — |
| `encode_documents_sparse()` | ✓ PASS | NONE | — |
| `encode_query_sparse()` | ✓ PASS | NONE | — |
| CrossEncoder setup | ✓ PASS | NONE | — |
| CUDA check | ✓ PASS | NONE | — |
| Integration | ✓ PASS | NONE | — |

---

## Recommendations

### MEDIUM-Priority Actions (address soon)

1. **Add edge-case tests for `parse_query()`:**
   - Test `type:` (no value) → should remain in text
   - Test `type:` (space) → should remain in text
   - Test `type:adr extra:unknown` → `extra` should not extract

2. **Clarify `search_all()` docstring:**
   - Document that graph reranking is **not** applied (graph only applies to `search_vault()`).
   - Explain the separate normalization strategy and its implication for source parity.

3. **Document `_normalize_minmax()` intent:**
   - Add comment explaining that separate normalization before merge creates equal weighting between sources (despite quality differences).

### LOW-Priority (nice-to-have)

1. **Test coverage for `_rerank()` with empty snippets:**
   - Verify CrossEncoder behavior when snippet is `""`.

---

## Audit Completion

- ✓ All 6 search.py targets audited
- ✓ All 5 embeddings.py targets audited
- ✓ Integration correctness verified
- ✓ No CRITICAL or HIGH severity issues found
- ✓ 2 MEDIUM-priority documentation/test improvements identified
