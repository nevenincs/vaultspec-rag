---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
step_id: 'S02'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

# Refactor VaultStore client initialization to bypass FileLock and connect to url

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Refactor `__init__` in `VaultStore` to read `qdrant_url` and `qdrant_api_key` from configuration wrapper.
- Bypass `FileLock` instantiation and acquisition if `qdrant_url` is configured.
- Establish `QdrantClient` connection using the server URL and API key.
- Fall back to standard local file-based Qdrant client connection and local directory locks if the URL is not set.

## Outcome

- The client can connect to an external or local Qdrant server without holding local filesystem lock files, resolving lock conflicts for concurrent instances.
