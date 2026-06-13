---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
---

# Round 10 Audit -- embeddings.py (deep dive)

**Auditor:** docs-researcher-2-2
**File:** `src/vaultspec_rag/embeddings.py` (322 lines)
**Cross-reference:** `src/vaultspec_rag/search.py` (CrossEncoder reranker lives here), `src/vaultspec_rag/config.py`
**Date:** 2026-03-07

______________________________________________________________________

## Check 1: SparseEncoder Methods

### `encode_documents_sparse()` (lines 274-307)

```python
sparse_tensor = self._sparse_model.encode_document(
    truncated,
    batch_size=batch_size,
)
```

Uses `encode_document()` (singular) -- the correct SparseEncoder method for documents. This was fixed from the original `encode()` call (Round 2 finding).

### `encode_query_sparse()` (lines 309-321)

```python
sparse_tensor = self._sparse_model.encode_query([query[:max_chars]])
```

Uses `encode_query()` -- the correct SparseEncoder method for queries.

**Verdict: PASS.** Both document and query sparse encoding use the correct role-specific methods (`encode_document` / `encode_query`), enabling SPLADE's asymmetric query/document prompts.

______________________________________________________________________

## Check 2: CrossEncoder Sigmoid

The CrossEncoder lives in `search.py`, not `embeddings.py`.

### `search.py:_get_reranker()` (lines 195-220)

```python
self._reranker = CrossEncoder(
    self._reranker_model_name,
    device="cuda",
    activation_fn=torch.nn.Sigmoid(),
)
```

**Verdict: PASS.** `activation_fn=torch.nn.Sigmoid()` is present. This maps CrossEncoder logits from (-inf, +inf) to (0, 1), fixing the negative-score graph boost bug (Task #64 / Round 5 finding).

______________________________________________________________________

## Check 3: Reranker Model

### `config.py` (line 29)

```python
"reranker_model": "BAAI/bge-reranker-v2-m3",
```

### `search.py` (line 192)

```python
self._reranker_model_name: str = cfg.reranker_model
```

**Verdict: PASS.** The reranker model is loaded from config, defaulting to `BAAI/bge-reranker-v2-m3`. This is the intended production model.

Note: CLAUDE.md still says `cross-encoder/ms-marco-MiniLM-L6-v2`. This is a documentation mismatch, not a code bug. The CLAUDE.md should be updated to reflect the actual model, or the discrepancy should be explicitly documented as intentional (ADR decision).

______________________________________________________________________

## Check 4: Dense Model Init

### `__init__()` (lines 168-183)

```python
model_kwargs = {
    "torch_dtype": torch.float16,
}
try:
    import flash_attn
    model_kwargs["attn_implementation"] = "flash_attention_2"
except ImportError:
    logger.info("flash_attention_2 not available, using default attention")

self._dense_model = SentenceTransformer(
    dense_name,
    model_kwargs=model_kwargs,
    tokenizer_kwargs={"padding_side": "left"},
)
```

**Verdict: PASS.** Uses `torch.float16` (not string), probes for `flash_attn` before adding `attn_implementation`, and passes `tokenizer_kwargs={"padding_side": "left"}` as required by Qwen3. The `model_kwargs` dict is passed directly -- sentence-transformers forwards this to `AutoModel.from_pretrained(**model_kwargs)`.

### R10-m1: `flash_attention_2` probe uses `import flash_attn` but `model_kwargs` key is `"attn_implementation"` (Minor)

The probe at line 174 imports `flash_attn` to check if the package is installed. This is correct -- `flash_attn` is the PyPI distribution name. The `model_kwargs` key `"attn_implementation"` is the HuggingFace Transformers config key, not the package name. These are correctly different things. No issue.

**Verdict: PASS (false alarm on initial read).**

______________________________________________________________________

## Check 5: Sparse Model dtype

### `__init__()` (lines 186-190)

```python
self._sparse_model = SparseEncoder(
    sparse_name,
    device="cuda",
    model_kwargs={"torch_dtype": torch.float16},
)
```

**Verdict: PASS.** Uses `torch.float16` (the actual dtype object), not the string `"float16"`. This was flagged as R22b-m13 and has been fixed.

______________________________________________________________________

## Check 6: OOM Retry Logic

### `encode_documents()` (lines 234-252)

```python
while True:
    try:
        embeddings = self._dense_model.encode(...)
        return ...
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if batch_size <= 1:
            raise
        batch_size = max(1, batch_size // 2)
        logger.warning(...)
```

OOM retry loop with batch halving. Correctly re-raises when batch_size is already 1.

### `encode_documents_sparse()` (lines 291-307)

Same OOM retry pattern. Correct.

### `encode_query()` (lines 254-272)

No OOM retry. Single query inference.

### `encode_query_sparse()` (lines 309-321)

No OOM retry. Single query inference.

**Verdict: PASS.** Document batch methods have OOM retry. Query methods (single inference) do not, which is acceptable -- a single query is unlikely to OOM, and if it does, the error should propagate. This was flagged as R22b-m10 and the current behavior is by-design.

______________________________________________________________________

## Check 7: CUDA Check

### `_check_rag_deps()` (lines 34-56)

```python
def _check_rag_deps() -> None:
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA GPU required. No CUDA device found. ..."
            )
    except ImportError:
        raise ImportError(
            "GPU RAG dependencies not installed. ..."
        ) from None
    try:
        import sentence_transformers
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. ..."
        ) from None
```

**Verdict: PASS.** Raises `RuntimeError` for missing CUDA, `ImportError` for missing packages. Both with clear messages. Called at top of `EmbeddingModel.__init__()` (line 153).

______________________________________________________________________

## Check 8: `_sparse_tensor_to_results`

### Lines 59-104

Handles three input types:

1. **scipy sparse** (line 68-77): Checks `hasattr(sparse_tensor, "tocsr")`, converts to CSR, iterates rows
1. **torch.Tensor** (line 79-91): Checks `isinstance(sparse_tensor, torch.Tensor)`, handles both `is_sparse`/`is_sparse_csr` and dense tensors
1. **numpy array** (line 93-104): Fallback using `np.asarray()`

### R10-m2: `is_sparse_csr` check on line 80 may raise `AttributeError` on very old PyTorch (Minor)

```python
if sparse_tensor.is_sparse or sparse_tensor.is_sparse_csr:
```

`is_sparse_csr` was added in PyTorch 1.10. The project requires CUDA and modern torch (likely 2.x+), so this is practically unreachable. This was flagged as R22b-m11 -- still present, still low risk.

**File:** `embeddings.py:80`

**Verdict: PASS overall.** All three tensor formats are handled correctly. The scipy path is the most likely for SparseEncoder output (SPLADE returns scipy sparse matrices).

______________________________________________________________________

## Check 9: `encode_documents` Truncation

### `encode_documents()` (lines 231-232)

```python
max_chars = self._default_max_embed_chars()
truncated = [t[:max_chars] for t in texts]
```

### `encode_documents_sparse()` (lines 288-289)

Same pattern.

### `encode_query()` (lines 254-272)

No truncation on queries. Query strings are typically short (user input), so this is acceptable.

### `encode_query_sparse()` (line 319)

```python
sparse_tensor = self._sparse_model.encode_query([query[:max_chars]])
```

Truncates queries for sparse encoding.

### R10-m3: `encode_query()` does not truncate query text (Minor)

`encode_query()` at line 267 passes `[query]` directly to `self._dense_model.encode()` without `[:max_chars]` truncation. While queries are typically short, a malformed or adversarial query could be very long. `encode_query_sparse()` does truncate (line 319). This inconsistency could cause the dense encoder to process an unexpectedly long input.

In practice, the SentenceTransformer tokenizer will truncate to `max_seq_length` (typically 512 or 8192 tokens depending on model config), so this is unlikely to cause OOM. But it's inconsistent with the sparse query path.

**File:** `embeddings.py:267-271`

______________________________________________________________________

## Check 10: Bare `except Exception`

Scanning all exception handlers in `embeddings.py`:

| Line | Handler                              | Assessment                            |
| ---- | ------------------------------------ | ------------------------------------- |
| 44   | `except ImportError`                 | Specific. Correct.                    |
| 52   | `except ImportError`                 | Specific. Correct.                    |
| 176  | `except ImportError`                 | Specific. Correct (flash_attn probe). |
| 243  | `except torch.cuda.OutOfMemoryError` | Specific. Correct (OOM retry).        |
| 298  | `except torch.cuda.OutOfMemoryError` | Specific. Correct (OOM retry).        |

**Verdict: PASS.** No bare `except Exception` in embeddings.py. All exception handlers are specific.

______________________________________________________________________

## Additional Observations

### `hasattr` checks on config (lines 163-166, 194-196)

```python
sparse_name = (
    cfg.sparse_model
    if hasattr(cfg, "sparse_model") and cfg.sparse_model
    else self.SPARSE_MODEL_NAME
)
```

`VaultSpecConfigWrapper.__getattr__` (config.py:36-41) provides defaults for all RAG keys including `sparse_model`, so `hasattr(cfg, "sparse_model")` is always `True`. The `hasattr` check is dead defensive code (R22b-m14). Same for `embedding_dimension` at lines 194-196.

Not a bug, just unnecessary code.

### `encode_documents` does not use `prompt_name` (line 236)

```python
embeddings = self._dense_model.encode(
    truncated,
    batch_size=batch_size,
    show_progress_bar=len(truncated) > 100,
    normalize_embeddings=True,
)
```

No `prompt_name` parameter. This was flagged as R22b-M4 and verified as **correct** (not a bug): Qwen3-Embedding-0.6B documents should be encoded without a prompt prefix. Only queries use `prompt_name="query"`. This is confirmed by the Qwen3 documentation and Research Topic 12.

______________________________________________________________________

## Summary

| ID     | Severity | Finding                                                                             |
| ------ | -------- | ----------------------------------------------------------------------------------- |
| R10-m2 | MINOR    | `is_sparse_csr` check may fail on PyTorch < 1.10 (practically unreachable)          |
| R10-m3 | MINOR    | `encode_query()` does not truncate query text (inconsistent with sparse query path) |

### Verified Fixes

| Prior Finding                                      | Status                                                       |
| -------------------------------------------------- | ------------------------------------------------------------ |
| Round 2: SparseEncoder uses generic `encode()`     | **FIXED** -- uses `encode_document()` / `encode_query()`     |
| R22b-m13: sparse model dtype is string `"float16"` | **FIXED** -- uses `torch.float16`                            |
| Task #64: CrossEncoder sigmoid activation          | **FIXED** -- `activation_fn=torch.nn.Sigmoid()` in search.py |

### Cross-file notes (search.py)

- CrossEncoder initialization at `search.py:210-214` is correct: `device="cuda"`, `activation_fn=torch.nn.Sigmoid()`, model loaded from config.
- Reranker model is `BAAI/bge-reranker-v2-m3` (config.py:29), contradicts CLAUDE.md which says `cross-encoder/ms-marco-MiniLM-L6-v2`. Documentation should be updated.

**0 HIGH/MEDIUM findings. 2 MINOR findings. All major prior findings verified as fixed.**
