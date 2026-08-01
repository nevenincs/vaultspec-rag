---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:96d797807f2d52a8624b1600077c203d9a7c3d4006bc95f191f5e529e550039d'
step_id: 'S99'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Include document collections in prefix pruning, debris classification, and storage maintenance routes

## Scope

- `src/vaultspec_rag/storage_ops.py`
- `src/vaultspec_rag/server/_routes_storage.py`

## Description

- Make prefix archive and removal targets deterministic.
- Aggregate document points in backend maintenance totals.
- Expose per-domain counts through the bounded service survey route.

## Outcome

Storage maintenance treats document collections as first-class namespace
members without encoding repository paths or client-specific layout.

## Notes

Static lint and type checks passed. Real maintenance behavior is verified in S124.
