---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S09'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Reconcile the manifest on service start and on root rename or move

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

Built the manifest reconcile that the shipped feature was missing. Added a `reconcile_manifest`
function to the storage manifest module that takes the set of prefixes the live server
currently backs and drops only the entries whose recorded root is gone AND whose data is
gone too - a conservative AND so a moved-but-still-stored namespace is preserved rather than
mislabelled unknown, and an offline-volume root is always kept. Added a companion
`rekey_prefix` that moves an entry to a root's freshly-derived prefix and updates its backend
in one atomic write, so a root rename or backend move does not leave a dangling key. Wired
the reconcile into the service startup: after the managed Qdrant is up and before models
load, a worker-thread call enumerates the server's collections, derives their per-root
prefixes, and reconciles - off the GPU lock, logged-and-swallowed on failure so a stale
manifest never aborts startup.

## Outcome

The manifest now self-heals on service start: stale bookkeeping for roots whose data the
operator already dropped is cleared, while live and unverifiable entries and entries whose
data still exists are preserved. The reconcile runs as pure storage IO on a worker thread,
never under the GPU lock, and is best-effort so it cannot wedge startup. Real-backend and
unit tests cover the drop, keep-live, keep-data-still-present, and rekey paths.

## Notes

The startup wiring integrates into the refactored startup helper that the recent
service-hardware-singleton work split out, placed after the qdrant-spawn block and guarded by
the server-mode check so local-only startups skip it.
