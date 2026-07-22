---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S105'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify raw and extracted document routes remain document-owned through real full and incremental indexing

## Scope

- `src/vaultspec_rag/tests/integration/test_document_indexing.py`

## Description

- Verify raw full, unscoped incremental, and scoped incremental indexing.
- Verify real extractor output remains document-owned with native metadata.

## Outcome

Real full and incremental tests cover raw and extracted document routing.

## Notes

Phase-boundary tests passed.
