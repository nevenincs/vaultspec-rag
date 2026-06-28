---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S04'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace rag-broker-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Unit-test the reorder and each --json outcome shape with an isolated temp status dir and ## Scope

- `src/vaultspec_rag/tests/test_cli_server_start.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Unit-test the reorder and each --json outcome shape with an isolated temp status dir

## Scope

- `src/vaultspec_rag/tests/test_cli_server_start.py`

## Description

- Added tests to `test_cli_server_start.py`: the `--json` envelope shapes via the helpers (already_running success, machine_owned failure-with-exit, human-mode emits no JSON); and the genuine guards LIVE via the CliRunner with an isolated singleton fixture - a real bound socket yields `port_in_use`, and a real `acquire_machine_lock` in-process yields `machine_owned` (holder pid == our pid).
- Asserted `_existing_service_running()` is `None` with an isolated empty status dir (the reorder's fall-through).

## Outcome

12 server-start tests pass. The JSON contract and the genuine guard outcomes are covered with no mocks (a real socket, a real machine lock); basedpyright and ruff clean.

## Notes

The live already_running/started paths need a real serving daemon (integration tier); the helper success-path test plus the existing `_existing_service_running` integration test cover the reorder's success side.
