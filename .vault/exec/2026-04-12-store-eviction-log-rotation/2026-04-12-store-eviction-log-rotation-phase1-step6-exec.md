---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-6

## goal

Migrate every MCP tool handler from `_registry.get_project(...)` to
`with _registry.lease(...)`, surface `RegistryFullError` as a
structured dict, and remove the temporary `get_project` alias.

## files touched

- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/service.py` (alias removal)
- `src/vaultspec_rag/tests/test_service_registry.py`
- `src/vaultspec_rag/tests/test_mcp_server.py`

## what was done

- Added `_registry_full_error_dict(exc)` helper returning the exact
  ADR D4 error shape (`ok`, `error`, `message`, `max_projects`,
  `busy_projects`).
- `_ensure_watcher` now calls `_registry.peek_project` (no refcount
  bump — watcher wiring is non-request-path).
- Wrapped `search_vault`, `search_codebase`, `get_index_status`,
  `reindex_vault`, `reindex_codebase`, and the stdio-only
  `get_vault_document` in `with _registry.lease(root) as slot: ...`,
  catching `RegistryFullError` in each tool handler and returning
  the structured error dict.
- Widened handler return types to `<Model> | dict[str, Any]`.
- `_ensure_watcher(root)` is only called after a successful
  (non-error) tool result.
- Removed the temporary `get_project = peek_project` class-level
  alias from `service.py`.
- Bulk-migrated every `.get_project(` in `test_service_registry.py`
  to `.peek_project(` (31 call sites).
- Added `TestRegistryFullErrorShape` in `test_mcp_server.py` with
  two unit tests: one checks the error-dict keys, the other asserts
  (via `inspect.getsource`) that `_ensure_watcher` uses
  `peek_project` and NOT `get_project`.

## deviations from plan

- The plan lists `get_code_file` among the handlers to wrap.
  `get_code_file` never touched `_registry` even in the pre-step-6
  code (it's pure file I/O rooted at `project_root`), so wrapping
  it in a lease would pay cold-start cost for a simple read.
  Left it untouched. Grep confirms zero `_registry.get_project`
  callsites in `mcp_server.py`.
- Used `isinstance(result, SearchResponse)` guard to skip
  `_ensure_watcher` on error-dict returns (rather than letting it
  fire against a project root that just hit `RegistryFullError`).

## test results

- `pytest src/vaultspec_rag/tests/test_mcp_server.py -m unit` ->
  89 passed (includes 2 new tests).
- `ruff check src/vaultspec_rag/` + `ty check src/vaultspec_rag`
  clean.
- Grep verification: `_registry\.get_project` returns zero matches.

## commit hash

`e157a2f feat(mcp): route tool handlers through ServiceRegistry.lease`

## time spent

~25 minutes.
