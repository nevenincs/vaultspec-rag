---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:c0d7d7a9c86c888d555fa120202f8db2acc80438dfa62acf6157523e3a392cd3'
step_id: 'S06'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Unit-test snapshot swap semantics, cached-list filtering, and freshness metadata alongside the routes tests

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Add `TestSurveySnapshot` (cold read, publish/read roundtrip, whole-snapshot replacement) and `TestGatherStorageSurveyCached` (cache hit never opens a client, filters/limit on the cached list, fresh recompute republishes, cold-cache fallback) to `src/vaultspec_rag/tests/test_storage_ops.py`
- Isolate each test with a `cold_snapshot` fixture that monkeypatches the slot to `None`

## Outcome

8 new unit tests; the cache-hit test proves the walk is skipped by making `_fetch_surveys` raise. Full unit tier: 1363 passed. Commit 7ae79ca.

## Notes

None.
