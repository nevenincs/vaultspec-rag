---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Namespace store collections per root in server mode via a stable short-hash prefix with instance-resolved collection names, unit-tested for stability and local-mode invariance

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/tests/test_store.py`

## Description

- Add `root_collection_prefix()` to `store.py`: blake2b-6 hash of the case-normalised,
  resolved root path rendered as `r{12-hex}_`, the stable per-root namespace for one
  shared server.
- Assign instance-level `TABLE_NAME` / `CODE_TABLE_NAME` in `VaultStore.__init__`:
  prefixed in server mode, bare in local mode; class attributes remain the bare
  local-mode names and the suffix. The per-collection lock dict is keyed by the
  resolved names so backend-aware locking is unchanged.
- Add `TestServerModeNamespacing` to `test_store.py`: prefix stability, path-spelling
  normalisation, per-root divergence, shape, local-mode invariance, and server-mode
  store wiring (two roots get different prefixed names against one URL).

## Outcome

38/38 store unit tests pass (7 new); ty strict and complexity gates green. No store
method needed changes - all point operations already reference the instance attributes.

## Notes

None.
