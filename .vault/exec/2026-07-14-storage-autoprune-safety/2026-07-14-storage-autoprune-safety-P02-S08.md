---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S08'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Prove lifecycle inertness with an import-graph regression test asserting no module reachable from the maintenance cycle imports the stop, terminate, or machine-singleton reclaim helpers

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Add `TestStorageMaintenanceIsLifecycleInert` to the ADR regression
  suite: a fresh-interpreter subprocess imports the maintenance modules
  (`storage_manifest`, `storage_ops`, `server._lifecycle`) and asserts no
  `vaultspec_rag.cli.*` module was pulled in; a source scan asserts none
  of them names `_terminate_and_confirm`, `_reclaim_machine_singleton`,
  `_stop_service_on_port`, or `_terminate_pid`.

## Outcome

2/2 passing; ruff and basedpyright clean. The invariant backing the
`storage-maintenance-is-lifecycle-inert` codification candidate is now a
regression gate.

## Notes

None.
