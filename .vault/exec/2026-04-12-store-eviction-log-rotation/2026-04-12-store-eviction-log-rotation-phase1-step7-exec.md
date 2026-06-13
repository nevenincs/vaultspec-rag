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

# store-eviction-log-rotation phase-1 step-7

## goal

Add `list_projects` and `evict_project` MCP tools per ADR D7.

## files touched

- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/tests/test_mcp_server.py`

## what was done

- `list_projects(project_root=None)` async MCP tool. Calls
  `_registry.snapshot()` inside `_run_in_thread`, derives a wall-
  clock `last_access_iso` from each entry's monotonic
  `idle_seconds`, returns `{projects, max_projects, idle_ttl_seconds}`
  matching the ADR D7 shape exactly. The `project_root` arg is
  accepted and ignored for signature parity.
- `evict_project(root)` async MCP tool. Resolves the path, looks
  up the slot under `_registry._lock`, returns `not_found` /
  `busy` / `forced` per ADR D7. Uses `close_project` for the
  eviction path so watcher teardown order is preserved.
- `TestAdminTools` test class: `test_list_projects_empty_registry`
  (N5 anti-tautology assertions against `get_config()`),
  `test_evict_project_unknown_returns_not_found`, and a tool-
  registration check.
- Updated the existing `TestToolRegistration::test_tool_count`
  and `test_expected_tools_registered` to account for the two
  new tools (6 -> 8).

## test results

- `pytest src/vaultspec_rag/tests/test_mcp_server.py -m unit` -> 92 passed.
- `ruff check` + `ty check src/vaultspec_rag` clean.

## deviations

None.

## commit hash

`31e4ff5 feat(mcp): add list_projects and evict_project admin tools`

## time spent

~15 minutes.
