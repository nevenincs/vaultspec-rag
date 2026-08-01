---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:0dbf0bf053a88e7cfbdddef8d7a920ca09707eb0da26134203520160f6fd75e3'
step_id: 'S01'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Declare the bounded-geometry target as shared constants and add a drift predicate that compares a live collection's optimizer segment target against it

## Scope

- `src/vaultspec_rag/storage_ops.py`
- `src/vaultspec_rag/store.py`

## Description

- Add `SERVER_WAL_CAPACITY_MB = 16` and `SERVER_SEGMENT_NUMBER = 2` to the torch-free leaf module `src/vaultspec_rag/store_schema.py`, with a comment recording the measured cost model, and export both from `__all__`.
- Rewire the collection-create path in `src/vaultspec_rag/store.py` to consume the shared constants instead of inline literals.
- Add the `GeometryEntry` dataclass and `read_geometry()` to `src/vaultspec_rag/storage_ops.py`, reading each live collection's `default_segment_number` and on-disk footprint.

## Outcome

The bounded geometry now has a single declaration that both creation and reconciliation read, so the two cannot drift apart. `read_geometry()` gives the maintenance and CLI surfaces a per-collection view of the configured segment target and footprint. Collections whose config cannot be read are omitted, because an unreadable collection is not evidence of drift.

## Notes

No incidents.
