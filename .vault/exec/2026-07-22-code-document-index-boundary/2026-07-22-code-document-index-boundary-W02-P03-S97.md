---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:3314dd33312358b8e82c3ec220bcdcd56c58f7a8f6c0f008534710e2b2b29e75'
step_id: 'S97'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Include document collections and metadata in snapshot manifests

## Scope

- `src/vaultspec_rag/storage_manifest.py`
- `src/vaultspec_rag/storage_ops.py`

## Description

- Define a deterministic namespace snapshot manifest contract.
- Record every archived collection, point count, schema version, and artifact.
- Preserve the independent document metadata sidecar beside the snapshots.

## Outcome

Completed archives now contain enough explicit collection and metadata evidence
to restore the document domain without repository-layout assumptions.

## Notes

Static lint and type checks passed. Real-server archive behavior is verified in S122.
