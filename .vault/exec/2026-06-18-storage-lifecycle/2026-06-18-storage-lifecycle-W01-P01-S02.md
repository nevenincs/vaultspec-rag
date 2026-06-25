---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S02'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Extend the server-mode test to assert a real hybrid search no longer returns the deleted file

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

Verified the shipped server-mode search-eviction assertion. Confirmed
`test_scoped_delete_evicts_code_chunks_and_search_in_server_mode` indexes a kept and a
doomed code module, proves both are searchable before deletion, deletes the doomed file,
runs the scoped incremental index, then asserts a real hybrid code search no longer
returns the deleted file while the kept module still surfaces.

## Outcome

The step is genuinely shipped. The test extends store-level eviction coverage with a real
hybrid search round-trip that must not surface the deleted file after the scoped reindex,
closing the issue-192 stale-result class in server mode. The survivor assertion
distinguishes true eviction from a search that simply stopped returning hits.

## Notes

No code changes; verify-and-tick of work delivered through pull request 196. The assertion
lives in the `TestServerModeDeletionEviction` class.
