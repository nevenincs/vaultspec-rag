---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S16'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Update runner tests: drop backend/staging/refusal cases, assert original-path invocation and preserved bounds/dispositions

## Scope

- `src/vaultspec_rag/tests/test_preprocess_runner.py`

## Description

- Drop `server_mode`/`unsandboxed` kwargs throughout.
- Replace the staged-remap case with an original-path assertion (hook echoes its argv path; no scratch-prefix leakage).
- Add a fresh-empty-scratch-cwd-cleaned-after test.
- Retain timeout kill, stdout cap, emitted cap, `on_error` dispositions, argv hygiene, and entry_point coverage.

## Outcome

Runner suite green; preserved bounds proven against the direct path.

## Notes

None.
