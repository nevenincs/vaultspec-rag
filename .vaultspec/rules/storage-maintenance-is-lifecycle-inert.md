---
derived_from:
  - "audit:2026-07-14-storage-autoprune-safety-audit"
---

# Storage maintenance is lifecycle-inert

## Rule

No storage-maintenance code path - survey, prune, delete, or the scheduled
auto-prune - may reach a service stop, terminate, or machine-singleton
reclaim helper. Maintenance is read/drop only, and the import graph is
regression-tested: nothing reachable from the maintenance modules may import
`vaultspec_rag.cli`.

## Why

The `2026-07-13` prune incident trace showed how a storage command that
shares a process and config surface with the lifecycle verbs pattern-matches
to "the prune killed the service" the moment anything terminates a daemon in
the same window - and a maintenance actor that genuinely could reach a
terminate flow would turn a routine reclamation into an outage. The
`2026-07-14-storage-autoprune-safety-adr` made inertness a hard invariant
when reclamation moved inside the daemon on a schedule.

## How

- **Good:** `TestStorageMaintenanceIsLifecycleInert` in
  `src/vaultspec_rag/tests/test_adr_regression.py` - a fresh-interpreter
  import of `storage_manifest`, `storage_ops`, and `server._lifecycle`
  asserts no `vaultspec_rag.cli.*` module loads, and a source scan asserts
  none of them names `_terminate_and_confirm`, `_reclaim_machine_singleton`,
  `_stop_service_on_port`, or `_terminate_pid`.
- **Bad:** importing a CLI lifecycle helper (even function-locally) from
  `storage_ops.py` or the maintenance tick, or adding a "restart the
  service if degraded" branch to a maintenance cycle.
