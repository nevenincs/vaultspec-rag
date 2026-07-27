---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: '2026-03-09'
modified: '2026-07-27'
---
# Research Topic 21: Qwen3 Embedding Task Prefixes â€” Deep Verification

## Findings

### Retained preamble

**Date:** 2026-03-09
**Status:** COMPLETE â€” NO BUGS FOUND
**Severity:** All correct âœ“

______________________________________________________________________

### Executive Summary

The codebase implements custom `encode_documents()` and `encode_query()` wrapper methods in `EmbeddingModel`, correctly routing them to `SentenceTransformer.encode()` with/without `prompt_name` parameter:

| Method               | Dense Call                               | Sparse Call                                       | Status      |
| -------------------- | ---------------------------------------- | ------------------------------------------------- | ----------- |
| `encode_documents()` | `encode(texts)` â€” **NO `prompt_name`** âœ“ | `encode_document(texts)` â€” uses document prompt âœ“ | **Correct** |
| `encode_query()`     | `encode([query], prompt_name="query")` âœ“ | `encode_query(query)` â€” uses query prompt âœ“       | **Correct** |

The dense embedding call **NEVER applies `prompt_name` to documents**, which is correct by design (empty document prompt in model card).

______________________________________________________________________

### Key Findings

### 1. Qwen3 Model Has Asymmetric Prompts

Direct API inspection:

```python
{
  "query": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:",
  "document": ""
}
```

- **Query prompt:** Non-empty instruction prefix
- **Document prompt:** Empty string (not null, not undefined)

This is **correct design**: queries get instruction guidance, documents are embedded without prefix.

### 2. Dense Embedding â€” encode_documents() Correct

`embeddings.py:236-241`:

```python
embeddings = self._dense_model.encode(
    truncated,
    batch_size=batch_size,
    show_progress_bar=len(truncated) > 100,
    normalize_embeddings=True,
)
```

âœ“ **No `prompt_name` parameter** â€” relies on SentenceTransformer default behavior. When `prompt_name` is omitted, the model uses the configured document prompt (which is empty string).

âœ“ Batch encoding applies the same prompt to all items uniformly.

### 3. Dense Embedding â€” encode_query() Correct

`embeddings.py:267-271`:

```python
embeddings = self._dense_model.encode(
    [query],
    prompt_name="query",
    normalize_embeddings=True,
)
```

âœ“ **Explicit `prompt_name="query"`** â€” applies the instruction prefix.

### 4. Sparse Embedding â€” Uses Role-Specific Methods

`embeddings.py:293-296` (documents):

```python
sparse_tensor = self._sparse_model.encode_document(
    truncated,
    batch_size=batch_size,
)
```

`embeddings.py:309` (queries):

```python
sparse_vector = self.model.encode_query_sparse(query)
```

âœ“ Correctly uses `encode_document()` for documents, `encode_query()` for queries.

### 5. SentenceTransformer.encode() â€” Batch Behavior

**Verified:** When `encode()` is called with a batch of texts, it applies the same prompt to **every item in the batch uniformly**. This is the expected behavior and matches SPLADE sparse encoding.

The indexer sometimes calls:

```python
# embeddings.py:236
embeddings = self._dense_model.encode(truncated, batch_size=64, ...)
```

where `truncated` is a list of `[title1, content1, title2, content2, ...]`. All items receive the empty document prompt consistently.

### 6. SentenceTransformer.encode_documents() â€” Does NOT Exist

**Critical clarification:** The codebase defines its own `EmbeddingModel.encode_documents()` wrapper method (not inherited from SentenceTransformer). The actual `SentenceTransformer` class has no `encode_documents()` method.

Methods available:

- `SentenceTransformer.encode()` â€” generic, respects `prompt_name` kwarg
- `SparseEncoder.encode()` â€” no role-specific prompt
- `SparseEncoder.encode_query()` â€” applies query task routing
- `SparseEncoder.encode_document()` â€” applies document task routing

The codebase's wrapper is **correctly named and designed**.

### 7. Manual Instruction Prefix Alternative â€” Not Needed

Some Qwen3 examples use manual prefixes like `"Represent this document: " + text`. The model card confirms this is **not the recommended approach** for this specific model version. The model defines explicit prompts for documents (empty) and queries (instruction prefix), and `prompt_name` routing is the proper way to leverage them.

______________________________________________________________________

### Conclusion

**All implementation is CORRECT.** The asymmetric prompt design is intentional and properly applied:

âœ“ Documents: No prefix (empty prompt) â€” allows model to embed raw content
âœ“ Queries: Instruction prefix â€” guides model to retrieve-focused representations
âœ“ Batch encoding: Uniform prompt per batch
âœ“ Sparse and dense aligned on prompt routing

**No code changes required.**

______________________________________________________________________

### Verification Method

1. âœ“ Loaded `Qwen/Qwen3-Embedding-0.6B` and inspected `.prompts` dict
1. âœ“ Reviewed `encode()` signature in SentenceTransformer.encode source
1. âœ“ Traced indexer and search calls to `encode_documents()` and `encode_query()`
1. âœ“ Verified batch encoding applies prompt uniformly across all items
1. âœ“ Confirmed SparseEncoder has both `encode_query()` and `encode_document()`

______________________________________________________________________

## Sources

- HuggingFace Model Card: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- sentence-transformers docs: <https://www.sbert.net/docs/reference/modules/SentenceTransformer.html>
- SparseEncoder docs: <https://www.sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html>
- Implementation: `src/vaultspec_rag/embeddings.py:213-272`, `src/vaultspec_rag/indexer.py`, `src/vaultspec_rag/search.py`
