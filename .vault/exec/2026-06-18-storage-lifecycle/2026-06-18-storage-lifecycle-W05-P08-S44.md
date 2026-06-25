---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S44'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Re-key the manifest prefix, root, and backend on migrate

## Scope

- `src/vaultspec_rag/registry.py`

## Description

Built the manifest re-key that migrate was missing. Investigated the shipped migrate path
and confirmed it copied collections and verified counts but never updated the manifest, so a
root migrated between backends kept its old backend label and a later survey would attribute
the moved data to the wrong backend. Added the atomic `rekey_prefix` helper to the manifest
module and called it from the migrate CLI command after a real (non-preview) migrate that
actually moved data: it re-derives the prefix from the resolved root and stamps the new
backend in one read-modify-write. The re-key is skipped on a dry-run and when nothing
migrated, and is best-effort so a manifest hiccup never fails an already-applied data move.

## Outcome

A backend migration now leaves the manifest consistent: the migrated root's entry carries the
new backend so survey, prune, and delete attribute the moved data correctly. The re-key only
fires after data actually moved, preserving the dry-run-previews-nothing contract. A real-
backend integration test migrates a collection and asserts the manifest backend flipped from
server to local; the manifest unit tests cover the in-place backend change and the stale-key
move.

## Notes

The prefix is derived from the resolved root path, which a backend migrate does not change, so
the re-key updates the backend under the same key; the stale-key branch of `rekey_prefix`
covers the future case where a root move changes the prefix.
