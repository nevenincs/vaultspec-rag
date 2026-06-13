---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S50'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Replace subprocess.run with a bounded Popen read capping captured stdout (PREPROCESS-003)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

Replaced `subprocess.run(capture_output=True)` with `_run_bounded`: a `Popen` whose stdout
and stderr are drained on dedicated threads (deadlock-free) but stop *storing* stdout past
`max(max_emitted_bytes * 4, 1 MiB)` and stderr past 64 KiB, so a runaway extractor cannot
spike memory before the cap fires (PREPROCESS-003). `_invoke_and_validate` skips when the
captured stdout exceeds the ceiling. The wall-clock timeout still bounds a child that keeps
producing.

## Outcome

Peak memory is bounded regardless of child output volume; timeout and exit-code handling
preserved.

## Notes

Reading-and-discarding past the cap avoids pipe-block deadlock; the timeout kills a wedged
child.
