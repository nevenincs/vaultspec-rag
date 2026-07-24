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

# Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already\_\* path, where already-paused and already-running return exit 0 with the already\_\* status and a genuine state change returns the changed status, each proven red-then-green

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
