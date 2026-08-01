---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b41db5a493566d283f7a3f0c09a205d257716349788ae171e06990532c73d6d4'
step_id: 'S82'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify code-only jobs launch no document extractor and code cleanup preserves document collection, metadata, and cache

## Scope

- `src/vaultspec_rag/tests/integration/test_document_lifecycle.py`

## Description

- Index a real source file beside an explicitly document-owned extractor input.
- Assert the code path never launches the document extractor.
- Clean only code state and verify document collection, metadata, and cache bytes.

## Outcome

Code indexing and code cleanup remain document-lifecycle inert. The document
point, published metadata sidecar, and extraction cache survive byte-for-byte,
and the document extractor is never launched.

## Notes

Scoped Ruff and Ty checks passed. The real CUDA and local-Qdrant lifecycle test
passed in 16.09 seconds and released its model and store resources.
