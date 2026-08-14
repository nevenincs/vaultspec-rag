---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:0c8753a758446944bfa7c70360243f0dade36eb63044f0caeebc02f43c142542'
step_id: 'S14'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S14 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation and ## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

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
