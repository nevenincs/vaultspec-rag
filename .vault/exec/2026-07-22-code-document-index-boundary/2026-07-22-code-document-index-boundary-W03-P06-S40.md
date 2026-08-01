---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:7dc819ba26a215ee98a02e588c5db53bf4e3965c9f72968aae1dfc62d3ee5ae9'
step_id: 'S40'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Publish hashes as converged metadata only for indexed or stable policy-rejected files

## Scope

- `src/vaultspec_rag/indexer/_code_meta.py`
- `src/vaultspec_rag/indexer/_document_meta.py`

## Description

- Publish code file states only after storage-confirmed convergence.
- Mark document metadata incomplete whenever extraction or chunk publication remains unresolved.

## Outcome

Failed files no longer gain hash-only certification, and the next incremental run retries them.

## Notes

The phase boundary verified repeated extraction attempts and incomplete metadata after a real failing subprocess.
