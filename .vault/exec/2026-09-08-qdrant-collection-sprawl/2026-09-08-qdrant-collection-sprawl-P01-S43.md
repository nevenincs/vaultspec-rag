---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:7b6efb93023e36de1de9a1294a3313f49709d75a63e4797c3b7c5e9329f6a87c'
step_id: 'S43'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Admit the client's non-2xx server-failure type into the shared transport class, so a server that answers with an error is treated the same as one that cannot answer

## Scope

- `src/vaultspec_rag/_qdrant_transport.py`

## Changes

- `M` `src/vaultspec_rag/_qdrant_transport.py`
- `M` `src/vaultspec_rag/cli/_service_storage.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_adversarial.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py` -> `pass`
