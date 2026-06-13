---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'S14'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# Author the indexing and retrieval architecture guide

## Scope

- `docs/indexing.md` (new file)

## Description

Created `docs/indexing.md` — a grounded, operator-facing guide to the
indexing and retrieval architecture. Every technical claim was verified against
the live source before writing.

**Sources read and cross-checked:**

- `src/vaultspec_rag/embeddings.py` — dense model `Qwen/Qwen3-Embedding-0.6B`
  (`MODEL_NAME`), 1 024-d (`DEFAULT_DIMENSION`), fp16, asymmetric
  `prompt_name="query"` for queries vs no prompt for documents, flash_attn2
  probe, 8 000-char truncation (`MAX_EMBED_CHARS`), 2 048-token `max_seq_length`
  cap; sparse model `naver/splade-v3` (`SPARSE_MODEL_NAME`), fp16, BERT-native
  512-token cap preserved, `encode_document`/`encode_query` asymmetric dispatch;
  OOM halve-and-retry on both dense and sparse paths.
- `src/vaultspec_rag/search/_searcher.py` — CrossEncoder `BAAI/bge-reranker-v2-m3`,
  `activation_fn=Sigmoid()`, lazy load + shared instance, candidate fetch
  `max(top_k × 4, 20)`, `reranker_batch_size` default 32 with OOM halve-retry;
  graph-TTL cache (double-checked locking, lock `_graph_lock`).
- `src/vaultspec_rag/store.py` — `TABLE_NAME = "vault_docs"`,
  `CODE_TABLE_NAME = "codebase_docs"`, cosine distance 1 024-d dense +
  `SparseVectorParams` sparse, payload indexes per collection,
  `RrfQuery(Rrf(k=60))` top-level query, per-`Prefetch` filters,
  `VAULTSPEC_RAG_QDRANT_URL` server mode, `VaultStoreLockedError` on concurrent
  local access, `EMBEDDING_DIM = 1024` constant.
- `src/vaultspec_rag/indexer/_vault_indexer.py` — blake2b incremental hash in
  `index_meta.json`, per-instance `_writer_lock`, streaming slice upsert.
- `src/vaultspec_rag/indexer/_codebase_indexer.py` — `.gitignore` + optional
  `.vaultragignore` pruning, 10 MB file size gate (`_MAX_FILE_SIZE`), `spawn`
  `ProcessPoolExecutor`, single GPU consumer thread + `queue.Queue`,
  `_CONSUMER_SHUTDOWN_TIMEOUT_S = 300.0`, byte gate `index_parallel_min_bytes`
  8 MiB in auto mode, `code_index_meta.json` blake2b hashes.
- `src/vaultspec_rag/indexer/_chunking.py` — 23-extension `LANGUAGE_MAP`,
  tree-sitter grammar names per language vs `None` for data formats, `TextSplitter`
  fallback for grammar-less formats.
- `src/vaultspec_rag/config.py` — all `_RAG_DEFAULTS` values: `embedding_batch_size=64`,
  `embedding_encode_batch_size=8`, `embedding_code_encode_batch_size=32`,
  `max_embed_chars=8000`, `embedding_max_seq_length=2048`,
  `index_chunk_workers=0`, `index_parallel_min_bytes=8*1024*1024`,
  `index_cache_flush_slices=8`, `reranker_batch_size=32`,
  `sparse_enabled=True`, `reranker_enabled=True`, `watch_enabled=True`,
  `watch_debounce_ms=2000`, `watch_cooldown_s=30.0`, `dense_backend="torch"`.
- `src/vaultspec_rag/watcher.py` — `watchfiles.awatch`, vault `.md` + code
  extension sets, scoped incremental reindex.

**Structure of the guide:**

- Overview — two-vector representation, RRF, reranker, graph boost
- Models — dense encoder, sparse encoder, CrossEncoder reranker (all three with
  model IDs, toggle env vars, OOM behaviour, and asymmetric encoding notes)
- Vector store — Qdrant local/server mode, collections, hybrid RRF with
  `Rrf(k=60)`, per-Prefetch filters, quantization options
- Indexing pipeline — vault doc indexing (frontmatter extraction, blake2b,
  writer lock, slice streaming); codebase indexing (tree walking, AST chunker
  vs TextSplitter, spawn process pool, single GPU consumer thread, content-hash
  dedup)
- Incremental vs rebuild — default incremental semantics, `--rebuild --type`
  requirement and destructive semantics
- Auto-reindex watcher — watchfiles, debounce, cooldown, `watch_enabled=0`
  pull-only path
- Configuration knobs table — 17 rows with env var, default, and purpose

## Outcome

`docs/indexing.md` created (236 lines before mdformat).
`mdformat docs/indexing.md` ran with exit 0 and no output — file is
mdformat-clean. All model IDs, dimensions, defaults, and constants verified
against the live code.
