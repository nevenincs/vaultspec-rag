---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S10'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add unit and real-backend tests for manifest write, read, and reverse-map

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_manifest.py`

## Description

Extended the manifest tests to cover the newly built reconcile and rekey, including the
real-backend half the shipped suite lacked. The existing unit module already round-tripped
write, read, reverse-map, classify, and remove; added unit tests asserting reconcile drops
an orphan with no backing data, keeps a live root, keeps an orphan whose data still exists,
preserves unrelated entries, and that rekey changes the backend in place and clears a stale
old key. Added two real-backend integration tests against the pinned Qdrant server: one
asserts reconcile drops a stale prefix while keeping an orphan whose collection still lives
on the server, the other migrates a collection and re-keys the manifest to the new backend
and asserts the recorded backend changed.

## Outcome

The manifest write/read/reverse-map plus the new reconcile and rekey are covered by both
isolated unit tests (status dir isolated via the real env seam) and real-backend integration
tests (real qdrant, isolated storage dir). All pass: the manifest unit module is green and
the two new integration tests pass against the live server.

## Notes

The status-dir isolation uses the real `VAULTSPEC_RAG_STATUS_DIR` env seam with `reset_config`,
no monkeypatch, matching the existing fixture; tests use relative imports per the
absolute-imports gate.
