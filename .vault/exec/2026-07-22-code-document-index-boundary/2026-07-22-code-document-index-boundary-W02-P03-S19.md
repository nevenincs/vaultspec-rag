---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:4a99a3a65ea8fdcb6718d8eabbc237f3cb8e5a432c0b5169397a00a8d632aff6'
step_id: 'S19'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add independent document metadata publication and compatibility markers

## Scope

- `src/vaultspec_rag/indexer/_document_meta.py`

## Description

- Define document file and generation metadata with explicit compatibility markers.
- Validate normalized paths, unique point IDs, sorted files, and complete fingerprints.
- Read strictly and publish canonical JSON atomically with a durable flush.

## Outcome

Document generations now have an independent sidecar whose schema, storage
generation, content kind, policy identity, and completeness are explicit.
Malformed or incompatible evidence cannot silently certify a collection.

## Notes

Formatting, lint, and type checks passed. Atomic read/write behavior will be
exercised with the phase's real temporary storage fixture.
