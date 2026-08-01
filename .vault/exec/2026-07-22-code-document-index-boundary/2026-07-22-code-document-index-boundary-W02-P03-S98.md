---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2e7cd867a025b96df3de871a28dcedaa201ad3370385fa0e051e56f97498d94b'
step_id: 'S98'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Migrate document collections idempotently between local and resident-service storage

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Derive migration mappings from the central storage schema.
- Include the document collection in both migration directions.
- Preserve the existing count-verified and replay-safe copy behavior.

## Outcome

Document collections now migrate with the other independently declared storage
domains without hardcoded client or repository structure.

## Notes

Static lint and type checks passed. Real migration replay is verified in S123.
