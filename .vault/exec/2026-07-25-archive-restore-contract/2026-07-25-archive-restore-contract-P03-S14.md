---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:f30c8edde800490144725891c092099bce02b4d3420d056cd0e4d19003e58bf9'
step_id: 'S14'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation - by import or by name.

## Outcome

The inertness regression in `src/vaultspec_rag/tests/test_adr_regression.py` now guards the restore direction alongside the terminate direction, with two guards because neither sees what the other does:

- an import-graph check in a fresh interpreter, asserting `vaultspec_rag.storage_restore` is absent from `sys.modules` after the maintenance modules load;
- a source scan asserting no maintenance source names `storage_restore`, `restore_archive`, or `RestoreRequest`.

The names are matched exactly rather than on the word "restore". `storage_manifest` legitimately defines `record_restored_archive` - the provenance write the restore itself calls - and `storage_reclamation` owns a private `_read_archive_records`. A substring guard on "restore" or "read_archive" would fire on both and be loosened away on its first false positive.

## Notes

Both guards proved, each failing alone while the other stayed green:

The import-graph guard was proved with a module that re-exports `restore_archive`, imported from `storage_survey_ops`. No maintenance source then names a forbidden symbol, so only the graph guard fired - which is the case that guard exists for, and the reason a source scan alone would be insufficient.

The source-scan guard was proved by naming `restore_archive` in `storage_survey_ops` without importing anything. It fired naming that module and that symbol while the graph guard stayed green.

A direct `import vaultspec_rag.storage_restore` trips both, because the import line carries the module name. That easy case was observed first and is noted in the class docstring so the transitive case is not mistaken for the only one tested.

No mutation was left on disk: the scaffold module was deleted and the maintenance source restored, both verified against `git status` before the commit.
