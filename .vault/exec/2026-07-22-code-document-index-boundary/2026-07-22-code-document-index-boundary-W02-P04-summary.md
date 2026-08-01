---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:76aa7753624d4cfad1cf65cc99da2165e33c448ae854c078a1a1d77203b3212b'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W02.P04` summary

Completed kind-aware ingestion with independent document models, storage
dispatch, full and incremental reconciliation, managed lifecycle, explicit
all-domain outcomes, and real integration coverage.

- Modified: `src/vaultspec_rag/_store_models.py`
- Modified: `src/vaultspec_rag/indexer/_chunk_worker.py`
- Modified: `src/vaultspec_rag/indexer/_streaming.py`
- Created: `src/vaultspec_rag/indexer/_document_indexer.py`
- Modified: `src/vaultspec_rag/indexer/__init__.py`
- Modified: `src/vaultspec_rag/api.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/service.py`
- Modified: `src/vaultspec_rag/registry.py`
- Modified: `src/vaultspec_rag/watcher.py`
- Modified: `src/vaultspec_rag/server/_watcher.py`
- Created: `src/vaultspec_rag/tests/integration/test_document_indexing.py`

## Description

Explicit document routes now produce `DocumentChunk` values that preserve
native locators, metadata, titles, sections, anchors, and extractor identity.
The document index owns its collection, sidecar metadata, counts, full rebuild,
unscoped incremental discovery, and scoped reconciliation while code indexing
remains source-only. Raw decodable routes use the same document path without
requiring an extractor. Combined indexing retains a separate result or error
for every domain so a partial failure stays visible.

Verification used the production embedding model and local Qdrant path. Both
raw and extracted document integration tests passed, including full, unscoped,
and scoped updates and negative assertions against code storage. Targeted Ruff
and ty checks also passed.
