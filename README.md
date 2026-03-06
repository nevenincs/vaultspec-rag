# VaultSpec-RAG

RAG module for vaultspec (ML-heavy extraction).

This module provides high-performance embedding, indexing, and search capabilities
for VaultSpec, optimized for CUDA GPUs.

## Features

- **Embeddings**: Sentence-transformers for high-quality document vectors.
- **Store**: LanceDB for efficient vector and full-text search.
- **Indexer**: Incremental indexing of vault documents.
- **Search**: Hybrid search (vector + FTS) with Reranking support.

## Development

This project uses `uv` for dependency management and `pre-commit` for linting.

```bash
uv sync
pre-commit install
```
