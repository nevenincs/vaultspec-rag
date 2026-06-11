---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S48'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Dispatch entry_point rules through the subprocess runner (interpreter -m entry runner) with timeout (D9 follow-up)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

Generalised `_build_argv` to build the subprocess argv from either form: a `command` is
shell-split with `{path}` substituted token-wise; an `entry_point` becomes
`[sys.executable, "-m", _ENTRY_RUNNER_MODULE, ref, path]`. Both then flow through the same
`_run_bounded` + validate + cap path, so `timeout_s` and isolation apply uniformly. The
worker gate now admits entry_point rules (D6/D9 follow-up).

## Outcome

entry_point runs end-to-end via `run_preprocessor` (`test_run_preprocessor_entry_point_ok`);
a raising or unresolvable entry_point is a per-file skip.

## Notes

No second code path - entry_point is the command path with a synthesised argv.
