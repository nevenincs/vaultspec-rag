---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S28'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify source and extracted units reach only their assigned collections through the real embedding and storage path

## Scope

- `src/vaultspec_rag/tests/integration/test_document_indexing.py`
- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Exercise real embedding and Qdrant storage for source and extracted inputs.
- Assert collection ownership and complete extracted payload fidelity.

## Outcome

Real integration coverage proves source and extracted units reach only their assigned collections.

## Notes

Phase-boundary tests passed.
