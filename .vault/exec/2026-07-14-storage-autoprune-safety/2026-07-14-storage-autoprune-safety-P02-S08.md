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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S08 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Prove lifecycle inertness with an import-graph regression test asserting no module reachable from the maintenance cycle imports the stop, terminate, or machine-singleton reclaim helpers and ## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
