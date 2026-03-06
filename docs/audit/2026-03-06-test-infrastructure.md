# Audit: Test Infrastructure

Feature: conftest.py, constants.py, HAS_RAG guards, test fixtures

## 2026-03-06 -- Review (Passes 17-26)

### HAS_RAG Guards: ALL UPDATED

All 7 test files needing GPU deps now check `("qdrant_client", "sentence_transformers", "torch")`.
Files using `HAS_GPU_RAG`: test_api_integration, test_embeddings, test_indexer_integration, test_performance, test_quality, test_robustness, test_search_integration.
Files checking only `qdrant_client`: test_store, test_store_codebase, test_store_integration (correct -- store-only tests).
Files with no guard: test_query, test_search_unit, test_indexer_unit (correct -- no external deps).

### Previous Issues (ALL RESOLVED)

- Task #23 [CRITICAL]: 10 test files checked for `("qdrant_client", "fastembed")`. FIXED.
- Task #33 [HIGH]: test_embeddings.py asserted device=="cpu", tested removed methods. FIXED.
- Task #15 [MEDIUM]: conftest.py missing `_code_table` and `_code_fts_dirty`. FIXED.
- .tolist() in conftest.py _fast_index: FIXED (Task #43).
- test_store_codebase.py [0.1]*768 vectors: FIXED (now 1024).
- Task #47 [LOW]: conftest.py:24 stale "fastembed" comment. FIXED (now says GPU-only).

### Open Issues

- Task #48 [LOW]: test_embeddings.py:74,83 "SparseEmbedding" docstrings.
- Task #49 [LOW]: LANCE_SUFFIX variable names in constants.py.

### bench_rag.py: FIXED (Task #44)

Import path and LanceDB references corrected. Uses `vaultspec_rag` and `.qdrant`.
