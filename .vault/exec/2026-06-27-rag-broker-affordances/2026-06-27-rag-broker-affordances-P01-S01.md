---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S01'
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
     The S01 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Changed `_existing_service_running` to return `tuple[int, int] | None` (the running pid/port) instead of `bool`, removing the inline `_print_lifecycle_lines` so one detection path serves both human and JSON output.
- Updated the two integration assertions in `test_daemon_survives_shell_exit.py` from `is False` to `is None` for the new contract.

## Outcome

Detection is now a pure return; the caller renders the human "already running" lines or the JSON envelope. The dead-status-file cleanup (issue #204) is unchanged.

## Notes

The only production caller is `service_start`; the integration test exercises the live detection path.
