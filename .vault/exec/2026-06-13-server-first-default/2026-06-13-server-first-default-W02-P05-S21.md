---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S21'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# honor --local-only in install_run by writing the local-only runtime selection so the setup choice persists to runtime

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/config.py`

## Description

- Add a local-only persistence layer to `config.py`: `persist_local_only(value)` writes
  a small JSON marker (`{"local_only": bool}`) atomically (`.tmp` + `os.replace`) into
  the managed service directory (`status_dir`, default `~/.vaultspec-rag`, overridable
  via `VAULTSPEC_RAG_STATUS_DIR`), and `read_persisted_local_only()` reads it back,
  treating a missing / malformed / unreadable marker as absent (`None`).
- Wire the persisted read into `_resolve_rag_default` for the `local_only` key as a new
  resolution rung between env override and module default, so precedence is
  explicit env/flag > persisted config > default; `effective_server_mode()` honours it
  unchanged.
- In `install_run`, after a non-dry-run provisioning pass, persist the explicit
  local-only choice (via `_persist_runtime_selection`) so a later `server start` selects
  the chosen backend without the operator re-passing `--local-only`. Gate persistence on
  the `provision` path so enrollment-only calls never write runtime state; degrade an
  `OSError` to a recoverable warning naming the runtime escape hatches.

## Outcome

- `install --local-only` persists the local backend; a subsequent `server start` in a
  fresh process with no flag and no env resolves `local_only=True` and
  `effective_server_mode()=False` from the marker.
- A plain server-mode install persists `local_only=False` (an unambiguous, deliberate
  server selection); a dry-run install never writes the marker.
- Round-trip, precedence (env-overrides-marker, marker-overrides-default), malformed-
  marker tolerance, and install-time persistence are covered by tests in
  `test_install_provision.py`. The store lives in the per-host, gitignored, test-
  isolatable managed dir, so the pure-Python wheel and the repository stay untouched.
  `ruff` and `ty` clean whole-tree.

## Notes

The persistence default `_STATUS_DIR_DEFAULT` is kept in lock-step with the
`status_dir` entry in `_RAG_DEFAULTS` via an import-time assertion, so the marker always
lands in the same directory the config resolves without importing the wrapper class the
helpers feed. No issues.
