---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:151b7b87e4e3863649be401d310e9e91897d9ed4f1d8e8134f43658ab47cb3dc'
step_id: 'S100'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify older and newer storage descriptors fail or migrate according to the direct-consumer compatibility contract

## Scope

- `src/vaultspec_rag/tests/integration/test_document_store.py`

## Description

- Validate the current document descriptor as self-compatible.
- Refuse an older descriptor missing the required document domain.
- Refuse a descriptor newer than the consumer's known schema version.

## Outcome

Direct consumers now have real regression coverage for fail-closed document
schema negotiation.

## Notes

Phase-boundary gate: 8 real-store tests passed.
