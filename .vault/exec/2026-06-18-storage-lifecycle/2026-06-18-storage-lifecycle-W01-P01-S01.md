---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S01'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a server-mode integration test that indexes two code files, deletes one, runs a scoped incremental index, and asserts the deleted file chunks are gone from the store

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

Reconciliation pass: verified the shipped server-mode eviction test rather than
re-authoring it. Confirmed `test_scoped_delete_evicts_in_server_mode` indexes two code
files, deletes one, runs a scoped incremental index over the deleted path, and asserts
the deleted file's chunks are gone from the real managed Qdrant server while the
surviving file's chunks remain.

## Outcome

The step is genuinely shipped. The test asserts the scoped reindex returns `removed == 1`,
that the deleted file's chunk ids are absent from the store, that the kept file's chunks
survive, and that the deleted path is dropped from the on-disk meta - all against the real
Rust engine in server mode, with no full rebuild. Verified present on the current branch
and exercised by the real-backend suite.

## Notes

No code changes; this is a verify-and-tick of work delivered through pull request 196. The
test belongs to the `TestServerModeRoundTrip` class in the named server-mode integration
module.
