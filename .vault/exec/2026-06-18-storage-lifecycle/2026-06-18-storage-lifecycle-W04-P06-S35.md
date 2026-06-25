---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S35'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Verify refcount and store-lock checks run before any drop and that no deletion touches a live server storage file

## Scope

- `src/vaultspec_rag/store.py`

## Description

Audited the destructive storage path against the requirement that no deletion touches a
live server storage file and that lock/attribution guards run before any drop. Confirmed
the per-root delete drops only through the live server's collection API
(`client.delete_collection`) and never calls a filesystem removal (`rmtree`, `unlink`, or
`os.rmdir`) on the server storage tree, so a drop can never corrupt the running engine by
deleting a file out from under it. Confirmed the canonical-prefix gate rejects any target
that is not an anchored `r{12 hex}_` prefix even under the unknown-namespace escape hatch,
so a crafted or empty prefix can never startswith-match foreign roots. Confirmed the
local-store migrate path runs the resolved-path containment check before opening any
on-disk store, rejecting parent traversal and symlink escape. Confirmed the store's own
drop primitives take the lifecycle lock before the collection lock, honouring the
backend-aware lock ordering.

## Outcome

The load-bearing data-safety guards are present and correct: server-mode drops are
collection-API only (never a live storage file), the destructive target must be a canonical
namespace prefix, the migrate local path is containment-checked, and drop ordering takes the
lifecycle lock first. The one spec-conformance gap is the daemon refcount slot-release
before a drop (the "return busy" contract): under the accepted CLI-direct architecture the
destructive verb opens its own client to the managed server and has no access to the
daemon's in-memory registry, so it cannot release a daemon-held slot. The audit recorded
this as a bounded, non-corrupting follow-up (a busy root yields collection-not-found until
re-ensured, not data loss), because the drop goes through the server API rather than the
filesystem.

## Notes

No code changes. The refcount slot-release before drop is architecturally precluded by the
accepted CLI-direct design (the registry lives in the daemon, unreachable from the CLI's own
client) and would require routing destructive verbs back through the superseded service
control plane the reconciliation deliberately did not build. It remains a tracked,
non-blocking follow-up; the corrupting failure mode it would prevent does not exist because
no destructive path touches a live storage file.
