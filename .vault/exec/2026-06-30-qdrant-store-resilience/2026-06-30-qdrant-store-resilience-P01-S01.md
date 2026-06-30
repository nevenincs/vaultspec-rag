---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-30-qdrant-store-resilience-plan]]"
---

# Add \_quarantine_collection that moves collections/<name> to collections/.quarantine/<name>.<timestamp>

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

Added the quarantine primitive `_quarantine_collection`.

## Outcome

Moves `collections/<name>` to a timestamped `quarantine/<name>.<ts>` sibling of `collections/` (never under it, or Qdrant would try to load the quarantine dir). The move is reversible and preserves the corrupt files; the root re-creates its collection on demand on next touch (QR2).

## Notes

Tested: real-FS move, healthy collections untouched, files preserved.
