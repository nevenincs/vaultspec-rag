---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S08'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests with a real echo-to-JSON script fixture: success, timeout, nonzero-exit, oversize, bad-json (D6, D9, D10)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_runner.py`

## Description

Added `test_preprocess_runner.py`: 9 tests driving a real Python extractor script written
to `tmp_path` and invoked through the runner (no mocks) - success with units+locator,
non-zero exit skip, bad-JSON skip, schema-invalid skip, real timeout skip, oversize-emission
skip, `on_error=fail` raises abort, `on_error=passthrough` returns passthrough, and a
path-with-spaces single-arg check.

## Outcome

9/9 pass (~1.1s, real subprocess); ruff clean. Covers D6/D9/D10 acceptance points.

## Notes

Interpreter and script paths are `shlex.quote`d so posix-mode split round-trips on Windows.
