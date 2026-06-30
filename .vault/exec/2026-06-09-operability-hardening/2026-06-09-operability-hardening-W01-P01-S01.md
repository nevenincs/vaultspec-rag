---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Spawn the daemon with the project venv interpreter, not ambient sys.executable

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Added `import sysconfig` to `_process.py` stdlib imports.
- Added `_resolve_daemon_interpreter() -> str` pure helper: resolves venv scripts dir via `sysconfig.get_path("scripts")`, picks `python.exe` (win32) / `python`, falls back to `sys.executable` when path absent.
- Replaced bare `sys.executable` in `_spawn_service` with `_resolve_daemon_interpreter()` to guarantee the project-pinned 3.13 interpreter is used, not a system 3.14.
- Added `src/vaultspec_rag/tests/test_process.py` with three `unit`-marked tests: path exists, lives under `Scripts`/`bin`, filename matches platform expectation.

## Outcome

`ruff check` and `ty check` both clean. Three unit tests pass.
Helper signature: `def _resolve_daemon_interpreter() -> str`.

## Notes

No incidents. `sys.executable` fallback is intentional to preserve behaviour in bare-interpreter or non-venv contexts.
