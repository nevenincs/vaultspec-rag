---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
step_id: 'S10'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Persist the service token into service.json during the start health-poll

## Scope

- `src/vaultspec_rag/cli/_service_status.py`
- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/__init__.py`

## Description

The daemon writes `service_token` into `service.json` on its first heartbeat
tick (~15 s after startup), but `service start` returns as soon as `/health`
reports `ready` — before the first heartbeat fires. Consequence: the CLI's
auto-delegation path reads the token from `service.json` and finds it absent,
causing 401 auth failures on every delegated request until the heartbeat lands.

### `_service_status.py`

Added `_update_service_token(token: str) -> None`:

- Reads the current `service.json` content.
- No-ops silently if the file is absent, unreadable, or already carries the
  same token.
- Merges `service_token` into the data dict and atomically rewrites via
  `.tmp` + `os.replace` (same pattern as `_write_service_status`).
- Never raises; OSError on write is debug-logged per the no-swallow rule.

### `_service_lifecycle.py`

In the health-poll success branch (after `health.get("status") == "ready"`):
reads `health.get("service_token")`; if it is a non-empty string, calls
`_update_service_token(token_from_health)` before printing the success panel
and returning.

### `cli/__init__.py`

Re-exported `_update_service_token` in the import block and `__all__` (sorted).

## Tests

`src/vaultspec_rag/tests/test_service_lifecycle_helpers.py`
`TestUpdateServiceToken`:

- `test_writes_token_into_existing_file` — token merged, existing fields preserved.
- `test_noop_when_file_absent` — no exception, no file created.
- `test_noop_when_token_already_matches` — mtime unchanged.
- `test_overwrites_stale_token` — old token replaced.
- `test_write_is_atomic_tmp_file_cleaned_up` — no `.tmp` artefact left.

All 5 tests use `VAULTSPEC_RAG_STATUS_DIR` isolation; no mocks.

## Outcome

`ruff check` and `ty check` both clean. 9 unit tests pass (5 directly covering
this step). End-to-end validation (token present in `service.json` before
first heartbeat) is covered by W04 integration re-validation.
