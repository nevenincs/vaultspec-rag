---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S04'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Serve the storage survey route from the snapshot with filters applied to the cached list, add computed_at and source envelope fields, and implement the fresh=true recompute-and-publish path

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Split the old `_gather_storage_survey` into `_fetch_surveys` (the O(namespaces) walk) and `_shape_survey_payload` (filters, limit, `queried_root`, freshness metadata) in `src/vaultspec_rag/server/_routes.py`
- Rebuild `_gather_storage_survey` as snapshot-first: cache hit shapes the cached list (`source: cache`), `fresh=True` or a cold slot runs the walk and republishes (`source: fresh`)
- Parse `?fresh=` on `storage_survey_route` (truthy set `1`/`true`/`yes`) and thread it through

## Outcome

The route is O(1) on the common path with `computed_at`/`source` in every envelope; the payload stays backward-compatible (new fields only). Commit 7ae79ca.

## Notes

Filters apply post-cache, so `?limit=` semantics are unchanged; `total` still counts post-filter namespaces.
