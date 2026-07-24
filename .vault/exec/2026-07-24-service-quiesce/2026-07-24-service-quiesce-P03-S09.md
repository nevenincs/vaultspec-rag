---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S09'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S09 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already_* path, where already-paused and already-running return exit 0 with the already_* status and a genuine state change returns the changed status, each proven red-then-green and ## Scope

- `src/vaultspec_rag/tests/test_service_quiesce_cli.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already_* path, where already-paused and already-running return exit 0 with the already_* status and a genuine state change returns the changed status, each proven red-then-green

## Scope

- `src/vaultspec_rag/tests/test_service_quiesce_cli.py`

## Description

- Added `test_service_quiesce_cli.py`: seven envelope-contract tests driving
  the verbs through `CliRunner` with the HTTP admin call stubbed, covering a
  genuine change, both idempotent `already_*` paths, both not-achieved
  failure paths, the unreachable path, and the exactly-one-envelope rule.

## Outcome

7 passed; ruff and ty clean on the changed files.

## Notes

Guard proof (guard-tests-prove-they-can-fail), one uninterrupted sequence:
the load-bearing not-achieved guard was mutated by forcing `achieved = True`
(trusting the verb instead of the re-read state). Both
`test_pause_that_did_not_hold_is_failure_exit_one` and
`test_resume_that_did_not_release_is_failure_exit_one` went RED on the
intended assertion (`assert 0 == 1` - the mutant returned exit 0 for a pause
that did not hold). The mutation was reverted and both returned GREEN.
