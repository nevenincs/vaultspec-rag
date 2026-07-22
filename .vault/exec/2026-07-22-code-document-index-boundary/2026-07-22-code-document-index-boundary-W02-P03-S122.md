---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S122'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify document collection and metadata appear in a real snapshot manifest

## Scope

- `src/vaultspec_rag/tests/integration/test_document_store.py`

## Description

- Create and snapshot a real namespaced document collection.
- Publish independent document metadata before the archive.
- Verify snapshot and metadata artifacts in the final manifest.

## Outcome

Real archives carry complete, explicit document recovery evidence.

## Notes

Phase-boundary gate: 8 real-store tests passed.
