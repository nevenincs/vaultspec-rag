---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S11'
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
     The S11 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Assert the attribution fields appear in the shutdown log line and the stop --json envelopes across the stop exit paths and ## Scope

- `src/vaultspec_rag/tests/test_cli_server_stop.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Assert the attribution fields appear in the shutdown log line and the stop --json envelopes across the stop exit paths

## Scope

- `src/vaultspec_rag/tests/test_cli_server_stop.py`

## Description

- Added a `TestShutdownAttribution` class: a shape test for `_initiator_fields`
  (pid equals the running process, bounded non-empty argv containing python or
  pytest, cwd is a real directory equal to the current one).
- Asserted through the real `_stop_success` helper that the initiator fields
  land in the `stopped` `--json` envelope `data`.
- Extended the existing `cleaned` outcome test to assert the initiator fields
  are absent, since that path terminates nothing.
- Added a live audit-line test that terminates a real non-python child
  (`cmd.exe ping` on win32 spawned in a new process group so CTRL_BREAK cannot
  reach the test runner, `sleep` on POSIX) under an isolated status dir and
  reads the isolated shutdown log, asserting the `cli_terminate` line carries
  `initiator_pid`, `initiator_cmd`, and `initiator_cwd`.

## Outcome

The full `test_cli_server_stop.py` plus `test_service_stop_port.py` run green
(17 passed). Ruff, ruff format, and basedpyright pass on the test file. No
mocks, patches, or skips.

## Notes

The child in the audit-line test is deliberately non-python and, on Windows,
spawned with `CREATE_NEW_PROCESS_GROUP`: the tokenless identity fallback would
confirm a python child as ours, and a CTRL_BREAK sent to a shared console
process group has previously killed a pytest run. No skipped work.
