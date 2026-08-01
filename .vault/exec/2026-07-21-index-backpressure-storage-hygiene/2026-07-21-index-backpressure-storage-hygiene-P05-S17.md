---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:d526626325b5ee33d979e70fe600f0b815777a510a887c415130f2492e5ce9e1'
step_id: 'S17'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# diff on-disk collection dirs against live qdrant collections into debris survey entries and add a total-backend-bytes rollup exposed via survey, server status, and /metrics

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

`debris_surveys` diffs on-disk collection dirs against the live server's
collection list; unmatched dirs surface as `debris` survey entries with
footprints, ranked among the attention-needing states. `backend_totals`
rolls up whole-backend bytes, namespace count, and per-status bytes;
served as `totals` on `/storage/survey` (computed pre-filter) and as new
`store_total_bytes`/`store_namespaces` gauges from the maintenance tick.

## Outcome

Committed within the P05 storage commit; `TestDebrisVisibility` green.

## Notes

`dangling_bytes` stays orphan-only; the totals are what make a pile of
live leaked namespaces visible.
