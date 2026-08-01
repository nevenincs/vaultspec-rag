---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:825b9512e3dea73feff7add6a8d5a1e827dc8e29cb978036ed7f8b9d530f2069'
step_id: 'S15'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# fold the unit text bound and the splitting parameters into the document content epoch so a bound change triggers rebuild

## Scope

- `src/vaultspec_rag/indexer/_config_epoch.py`

## Description

- Thread a `DocumentChunkingPolicy` snapshot (chunk chars, overlap, unit text max) through `ResolvedIndexPolicy` (field, pickle reduce, `resolve_index_policy` from config).
- Extend `resolved_policy_fingerprints` and `_per_kind_fingerprints` with a `document_chunking` payload folded into the DOCUMENT kind's content identity only.

## Outcome

Changing the bound, the ratio, the overlap, or the model window re-fingerprints the document content epoch and triggers a rebuild instead of leaving previously unsplit points silently stale; the code kind's identity is unaffected.

## Notes

Snapshot purity is preserved: the values resolve once in `resolve_index_policy` and travel with the pickled policy, so workers never re-read config.
