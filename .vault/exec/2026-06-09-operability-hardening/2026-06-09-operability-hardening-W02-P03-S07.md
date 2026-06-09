---
step_id: S07
tags:
  - '#exec'
  - '#operability-hardening'
date: 2026-06-09
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# operability-hardening W02-P03-S07

## Summary

Convert missing `project_root` into HTTP 400 with a clear message, not a 500.

## Changes

**`src/vaultspec_rag/server/_utils.py`**

- Added `ProjectRootRequiredError(ValueError)` — a distinct subclass so routes can
  catch it precisely without swallowing other `ValueError`s.
- `_default_root()` now raises `ProjectRootRequiredError` (was bare `ValueError`).
- Updated docstrings for `_default_root` and `_resolve_root` to reflect the
  precise exception type.

**`src/vaultspec_rag/server/_routes.py`**

- Added `ProjectRootRequiredError` to the top-level import from `._utils`.
- Added module-level constant `_BAD_REQUEST_MISSING_ROOT` (a reusable
  `JSONResponse` with `status_code=400`, `error="bad_request"`, and an
  actionable message naming `project_root`).
- Wrapped `_resolve_root(project_root)` in `try/except ProjectRootRequiredError`
  in five route handlers: `search_route`, `reindex_route`,
  `get_service_state_route`, `code_file_route`, `vault_document_route`, and
  `benchmark_route`.

**`src/vaultspec_rag/server/__init__.py`**

- Added `ProjectRootRequiredError` to the `from ._utils import (...)` block and
  to `__all__` (sorted per RUF022).

**`src/vaultspec_rag/tests/test_server.py`**

- Added `ProjectRootRequiredError` to the top-level server import.
- Added `TestProjectRootRequiredError` (4 unit tests): verifies subclass contract,
  that `_default_root()` raises the right type in HTTP mode, that `_resolve_root(None)`
  raises the right type in HTTP mode, and that the message names `project_root`.
- Added `TestRouteMissingProjectRoot` (5 route-level tests): uses `Starlette`
  `TestClient` with a live token to exercise `search_route`, `reindex_route`,
  `get_service_state_route`, `code_file_route`, and `vault_document_route` —
  each returns `{"ok": false, "error": "bad_request"}` with HTTP 400 when
  `project_root` is absent in HTTP mode. No mocks, no GPU, validation fires
  before any model/store access.

## Verification

- `ruff check` — all checks passed (0 violations).
- `ty check` — all checks passed (0 diagnostics).
- `pytest TestProjectRootRequiredError TestRouteMissingProjectRoot` — 9/9 passed.
- `pytest test_server.py` — 114 passed, 1 pre-existing failure
  (`test_vault_resource_raises_in_http_mode`, also failing on `main`).
