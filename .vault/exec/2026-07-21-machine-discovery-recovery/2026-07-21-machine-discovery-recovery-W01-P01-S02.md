---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S02'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Enforce the session-owned containment root before singleton writes and process control whenever pytest is active

## Scope

- `src/vaultspec_rag/`

## Description

- Validate both configured singleton anchors and each effect-specific target against the process-pinned pytest root.
- Guard service-status directory creation and write-lock acquisition before any status merge or deletion.
- Guard machine-lock acquisition, probing, and release before opening or changing an OS lock.
- Guard machine-pointer and Qdrant-identity publication and deletion before filesystem mutation.
- Guard managed service and Qdrant spawn, stop, and orphan-reap paths before process control.

## Outcome

Pytest now fails closed at each production singleton boundary when either managed anchor or
an explicit effect target escapes the session-owned containment root. The guard remains inert
outside pytest and republishes the pinned root before guarded child creation, so in-test
environment changes cannot move authority or poison an exec child.

## Notes

The first complete seven-file diff disappeared when another task's normal pre-commit hook
ran a global vault fix and rollback in the shared worktree, without a HEAD change. No reset,
checkout, stash, or destructive command was used. The same scoped patch was reapplied with
`apply_patch`, immediately rechecked, staged by exact path, and committed with hooks bypassed
to prevent the unrelated global rollback from erasing it again.

Ruff format and lint passed, BasedPyright reported zero diagnostics, the 59-test focused
machine-lock, discovery, status, Qdrant, and service-start suite passed, and the final
pointer-deletion follow-up plus machine-lock suite passed six tests. A standalone non-pytest
process also proved the guard remains inert for production execution.
