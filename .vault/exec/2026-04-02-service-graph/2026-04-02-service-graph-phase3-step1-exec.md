---
tags:
  - '#exec'
  - '#service-graph'
date: 2026-04-02
modified: '2026-06-30'
related:
  - '[[2026-04-02-service-graph-phase1-plan]]'
---

# service-graph phase-3 step-1: fastmcp lifespan + health endpoint

## Completed

Refactored `mcp_server.py` to use `ServiceRegistry` from Phase 2,
added `service_lifespan` async context manager for eager model loading,
`/health` endpoint, Starlette app composition, and `project_root`
parameter on all MCP tools.

## Changes

- `src/vaultspec_rag/mcp_server.py` — major refactor:

  - Removed `RagComponents` dataclass, `get_comp()`, `_comp`,
    `_comp_lock`, `_comp_error`, and module-level `_graph_cache`
  - Added module-level `_registry = ServiceRegistry()` and
    `_start_time` for uptime tracking
  - Added `_default_root()` and `_resolve_root()` helpers
  - Added `service_lifespan` async context manager: CUDA check
    with timing, HF cache logging, eager `_registry.load_model()`
    via `anyio.to_thread`, shutdown calls `_registry.close_all()`
  - Added `health_handler` async Starlette handler returning JSON
    with `status`, `cuda`, `models_loaded`, `projects`, `uptime_s`
  - Added `HealthResponse` Pydantic model
  - All 7 MCP tools now accept `project_root: str | None = None`
    and use `_resolve_root()` + `_registry.get_project(root)` +
    `slot.searcher` / `slot.store` etc.
  - `reindex_vault` uses `slot.graph_cache.invalidate()` instead
    of direct `_graph_cache.invalidate()`
  - `_ensure_watcher()` takes a `root: Path` argument and gets
    the slot from the registry
  - `main()` in HTTP mode builds `Starlette(routes=[Mount("/mcp", mcp.streamable_http_app()), Route("/health", health_handler)], lifespan=service_lifespan)` and runs `uvicorn.run()`
  - `main()` in stdio mode keeps `mcp.run(transport="stdio")`
  - `FastMCP("VaultSpec Search", stateless_http=True)` for
    multi-agent access
  - `vault://{doc_id}` resource and `analyze_feature` prompt
    preserved unchanged

- `src/vaultspec_rag/embeddings.py` — timing logs:

  - Added `import os, time` at module level
  - Added HF cache directory log at start of `__init__`
  - Added `time.perf_counter()` timing around dense model load
    and sparse model load with per-model log messages

- `src/vaultspec_rag/tests/test_mcp_server.py` — updated tests:

  - Removed `TestGetCompFailureCaching` and
    `TestRagComponentsDataclass` classes (old API removed)
  - Added `TestResolveRoot` (5 tests): explicit path, None
    fallback, env var resolution, `_default_root()` variants
  - Added `TestServiceRegistryIntegration` (3 tests): registry
    type check, gpu_sem type check, stateless_http enabled
  - Added `TestHealthHandler` (2 tests): JSON response structure,
    model state reflection (uses Starlette TestClient)
  - Added `test_tools_accept_project_root`: verifies all 7 tools
    have the `project_root` parameter in their input schema
  - Added `test_health_response` and `test_health_response_defaults`
    for the new HealthResponse Pydantic model

- `src/vaultspec_rag/tests/test_adr_regression.py` — updated:

  - `test_mcp_comp_lock_exists` renamed to
    `test_mcp_registry_lock_exists`, checks `_registry._lock`
  - `test_reindex_vault_resets_graph_cache` assertion updated to
    match `slot.graph_cache.invalidate()` pattern

## API compatibility

- `mcp.streamable_http_app()` confirmed available (returns
  `starlette.applications.Starlette`)
- `stateless_http=True` is a `FastMCP.__init__` constructor
  parameter (mcp>=1.26.0)
- FastMCP also has a `lifespan` constructor parameter, but we use
  Starlette's lifespan instead (needed to compose the `/health`
  route alongside the MCP mount)
- `starlette`, `uvicorn` both available as transitive dependencies

## Test results

- 239 unit tests pass (0 failures, 0 errors)
- 36 mcp_server tests pass (including 2 new health handler tests
  using Starlette TestClient)
- ruff check and ruff format clean on all modified files
