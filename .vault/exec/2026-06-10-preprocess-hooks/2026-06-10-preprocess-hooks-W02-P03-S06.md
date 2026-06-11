---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S06'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Implement the command runner: path substitution, subprocess.run timeout, stdout JSON parse, and on_error semantics (D6, D9)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

Added `_preprocess_runner.py`: `run_preprocessor(source_path, rule, *, max_emitted_bytes)` splits the command with `shlex.split` and substitutes `{path}`
token-wise (no shell), runs it via `subprocess.run` with `timeout=rule.timeout_s`, parses
stdout JSON, and validates against the schema. Recoverable failures (launch error, non-zero
exit, timeout, bad JSON, schema-invalid, over-cap) raise an internal skip signal mapped to
`on_error`: `skip` -> `skipped`, `passthrough` -> `passthrough`, `fail` -> raises
`PreprocessAbortError` (D6, D9). Running in a subprocess grandchild keeps the worker
CPU-only by construction.

## Outcome

Runner complete; ruff + basedpyright zero. `{path}` substitution is post-split, so paths
with spaces/metacharacters cannot inject.

## Notes

Only the command form is wired (D9); the loader already drops entry_point rules.
