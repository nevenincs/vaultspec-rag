---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S01'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary

## Scope

- `src/vaultspec_rag/tests/conftest.py`

## Description

- Force both singleton environment paths beneath one session-owned temporary root regardless of ambient values.
- Reset the core and RAG configuration caches on every force and restore boundary.
- Restore the canonical paths before and after every test and restore ambient values only after the session.
- Expose the canonical path mapping as an immutable view so fixture consumers cannot poison later rearming.
- Preserve verified read-only access to the host's pinned Qdrant binary through an isolated session mirror.
- Verify real heartbeat, discovery, identity, and lock paths remain inside pytest-owned storage.

## Outcome

The entire test session now owns both managed singleton paths. Missing, non-empty, or
cached path changes from one test cannot expose later tests to the operator's service
state, and the immutable session mapping preserves the rearm authority.

## Notes

Hostile-ambient and 24 focused real-behavior checks passed with the external trap
untouched. Ruff, targeted ty, strict BasedPyright, formatting, and diff checks passed.
The production fail-closed containment guard remains assigned to the next Step.

A later live-fixture run exposed that unconditional status isolation also hid the host's
verified Qdrant installation before nested service fixtures could mirror it. The session
fixture now resolves the pinned binary and manifest before isolation, copies them only into
the pytest-owned status tree, and protects both environment mutation and copying with the
same restoration `try/finally`. The safe mirror test and independent re-review passed with
no remaining findings; host binary, manifest, identity, and service state were unchanged.
