---
tags:
  - '#plan'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-06-30'
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-04-02-service-graph-research]]'
  - '[[2026-04-02-release-readiness-audit]]'
  - '[[2026-03-09-graph-embedding-round36-audit]]'
---

# `service-graph` phase-1 plan

Implement the service orchestration layer for vaultspec-rag, addressing
issues #16 (service layer + startup hangs) and #14 (graph rebuild race
R36-C1). This plan implements decisions D1-D6 from the accepted ADR,
creating a global resident service with multi-project routing, unified
graph ownership, FastMCP lifespan for eager model loading, and
dmypy-style CLI service commands.

### Phase `P01` - Graph cache unification

Give the vault graph one owner with a time-to-live and a lock, injected into the searcher, so a concurrent rebuild can no longer race.

- [x] `P01.S01` - Promote the private graph cache to a shared owner carrying a time-to-live and a lock, so concurrent readers at the expiry boundary rebuild once rather than racing; `src/vaultspec_rag/api.py`.
- [x] `P01.S02` - Inject the graph provider into the searcher rather than letting it build its own, and remove the external rebuild poke that worked around the missing ownership; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P01.S03` - Prove with a concurrent test at the expiry boundary that many threads produce exactly one rebuild; `src/vaultspec_rag/tests/`.

### Phase `P02` - Service registry

Introduce the registry that owns one shared embedding model and a per-project slot holding that project's store, searcher, indexers, graph cache and watcher.

- [x] `P02.S04` - Introduce the service registry owning one shared embedding model and a per-project slot for the store, searcher, indexers, graph cache and watcher, with explicit project-open, project-close and health entry points; `src/vaultspec_rag/service.py`.
- [x] `P02.S05` - Delegate the module-level engine accessor to the registry so a single resident instance backs every caller; `src/vaultspec_rag/api.py`.
- [x] `P02.S06` - Prove two project roots share one embedding model by object identity while keeping independent stores and caches; `src/vaultspec_rag/tests/`.

### Phase `P03` - Lifespan, health and multi-project tools

Load the model eagerly at startup behind a lifespan, expose a health endpoint reporting readiness, and let every tool address a project explicitly.

- [x] `P03.S07` - Load the embedding model eagerly during the server lifespan so the first request does not pay startup cost, and report load timing where an operator can see it; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P03.S08` - Expose a health endpoint reporting readiness and the resident project state, served from an explicit application rather than the framework default runner; `src/vaultspec_rag/server/_routes.py`.
- [x] `P03.S09` - Let every tool address a project explicitly so one resident service can serve several roots concurrently; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P04` - Service control verbs

Add the start, stop, status and warmup verbs over a status file recording the port and process, each verifying liveness before acting.

- [x] `P04.S10` - Add the service spawn helper and the status-file read and write helpers recording the port and process identity; `src/vaultspec_rag/cli/_process.py`.
- [x] `P04.S11` - Implement the start, stop and status verbs, each probing the port and verifying process liveness before acting, and tolerating a stale status file; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P04.S12` - Add the warmup verb reporting device availability and model cache state, and cover the start and stop lifecycle over an ephemeral port including the stale-status recovery; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

## Description

The ADR specifies 8 decisions (D1-D8), of which D7 (Rust Windows
Service) and D8 (Granian) are deferred to beta. The remaining 6
decisions are ordered by dependency:

- D3 (graph cache) is foundational -- no dependencies.
- D6 (ServiceRegistry) is the new state management kernel that D5
  (lifespan) and D2 (health) build on.
- D1 (daemon) and D4 (warmup) build on D2 for health/readiness.

The plan introduces one new file (`service.py`) and modifies existing
modules (`api.py`, `search.py`, `mcp_server.py`, `embeddings.py`,
`cli.py`).

## Steps

- Phase 1: Graph cache unification (D3 -- fixes R36-C1)

  1. Extend `_GraphCache` in `api.py` with TTL support: add
     `_built_at: float` field, accept `ttl_seconds` in constructor,
     check `time.monotonic()` inside the existing lock. Rename class
     to `GraphCache` (public, used by other modules).
  1. Add `graph_provider` parameter to `VaultSearcher.__init__` in
     `search.py`: `Callable[[], VaultGraph | None] | None = None`.
     When set, `_get_graph()` delegates entirely to it and the internal
     `_cached_graph` / `_graph_built_at` fields are unused. When `None`,
     falls back to internal cache with lock+TTL (add `threading.Lock`
     to the internal fallback path).
  1. Tests: concurrent `GraphCache.get()` at TTL boundary (N threads,
     verify single `VaultGraph` construction), `VaultSearcher` with
     and without `graph_provider`, invalidation after reindex.

- Phase 2: ServiceRegistry module (D6)

  1. Create `service.py` with `ServiceRegistry` class: shared
     `EmbeddingModel` (loaded via `load_model()`), per-project
     `ProjectSlot` (VaultStore + VaultSearcher + indexers +
     GraphCache) in `dict[Path, ProjectSlot]`, per-slot locking,
     `get_project(root)` for lazy per-project init,
     `close_all()` for shutdown.
  1. Wire `GraphCache` into each `ProjectSlot`: create per-project
     instance, pass `lambda: graph_cache.get(root)` as
     `graph_provider` to `VaultSearcher`. Invalidation via
     `graph_cache.invalidate()` after reindex.
  1. Refactor `api.py`: `get_engine()` delegates to
     `ServiceRegistry.get_project()`. `_Engine` becomes internal
     adapter. Public API (`index`, `search_vault`, etc.) unchanged.
  1. Tests: two project roots sharing one model (object identity
     check on `EmbeddingModel`), independent Qdrant stores,
     independent graph caches, concurrent `get_project()` calls.

- Phase 3: FastMCP lifespan + health endpoint (D5 + D2)

  1. Implement `service_lifespan` async context manager in
     `mcp_server.py`: startup calls `registry.load_model()` with
     per-stage timing logs (CUDA check, cache status, dense load,
     sparse load, reranker load, total). Shutdown calls
     `registry.close_all()`.
  1. Add `health_handler` in `mcp_server.py`: returns JSON with
     `status`, `cuda`, `models_loaded`, `projects` list,
     `uptime_s`. Available only after lifespan completes.
  1. Replace `mcp.run()` with explicit Starlette app:
     `Starlette(routes=[Mount("/mcp", mcp.streamable_http_app()), Route("/health", health_handler)], lifespan=...)`. Call
     `uvicorn.run()` with `timeout_graceful_shutdown=30`.
  1. Enable `stateless_http=True` on FastMCP for multi-agent.
  1. Refactor all MCP tools to accept optional `project_root`
     parameter, resolve to `Path`, call
     `registry.get_project(root)`. Remove old `get_comp()`
     and `RagComponents`.
  1. Refactor `EmbeddingModel.__init__` in `embeddings.py` to log
     per-model timing and HuggingFace cache directory.
  1. Tests: health endpoint returns correct state, reflects multiple
     connected projects. MCP tools with explicit `project_root`.

- Phase 4: Service daemon commands (D1 -- dmypy pattern)

  1. Add `_spawn_service()` helper in `cli.py` encapsulating
     platform-specific subprocess creation (Windows
     `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` vs Unix
     `start_new_session`). Accept port, log path. Return PID.
  1. Add `_read_service_status()` and `_write_service_status()`
     helpers for `~/.vaultspec-rag/service.json` (global: pid,
     port, started_at). Add `_is_pid_alive()` with platform check.
  1. Implement `service start`: TCP port probe (detect running
     service), stale status recovery, spawn via `_spawn_service()`,
     poll `GET /health` with exponential backoff (100ms-5s, 30s
     timeout), print readiness with startup timing.
  1. Implement `service stop`: read status, verify PID, terminate
     (SIGTERM / TerminateProcess), remove status file. Uvicorn
     drains with `timeout_graceful_shutdown=30`.
  1. Implement `service status`: read status, PID liveness, health
     probe, Rich output (running/stopped, uptime, port, GPU,
     connected projects, document counts per project).
  1. Tests: start/stop lifecycle with ephemeral port, stale status
     recovery, port-in-use handling. Platform abstraction via
     `_spawn_service()`, 5s health-poll timeouts.

- Phase 5: Model prefetch (D4)

  1. Add `service warmup` command in `cli.py`: CUDA check,
     `huggingface_hub.snapshot_download()` for all 3 model repos
     with Rich progress bars, cache status reporting per model,
     `HF_HUB_DOWNLOAD_TIMEOUT` defaulting to 60s.
  1. Tests: verify warmup checks CUDA, reports cache status.

## Parallelization

- **Phase 1** runs first (graph cache is foundational).

- **Phase 2** depends on Phase 1 (ServiceRegistry creates per-project
  `GraphCache` instances wired via `graph_provider`).

- **Phase 3** depends on Phase 2 (lifespan calls `registry.load_model()`,
  MCP tools call `registry.get_project()`).

- **Phase 4 and Phase 5** can execute in parallel after Phase 3.
  Phase 4 (daemon) polls `/health`. Phase 5 (warmup) is independent.

Recommended execution:

- Sequential: Phase 1 → Phase 2 → Phase 3
- Parallel: Phase 4 + Phase 5 (two agents, after Phase 3)

## Verification

- **R36-C1 fix**: concurrent `GraphCache.get()` test with N threads
  at TTL boundary verifies exactly one `VaultGraph` construction.

- **Multi-project isolation**: two project roots registered via MCP
  tools produce independent search results, independent graph caches,
  and share the same `EmbeddingModel` instance (verified by object
  identity check).

- **No regression**: all 220+ existing unit tests pass. `VaultSearcher`
  constructor change is backward-compatible. `api.py` public API is
  unchanged.

- **Service lifecycle**: `service start` → `GET /health` returns ready
  → search via `--port` from two different project dirs → `service stop`
  → `GET /health` connection refused. Verified on Windows.

- **Eager loading**: service log shows per-stage timing. `/health`
  returns 200 only after all models loaded. No cold-start on first
  consumer request.

- **Multi-agent**: two concurrent HTTP clients can search different
  projects simultaneously without interference.

- **Health endpoint**: raw HTTP GET (not MCP tool call), returns JSON,
  includes per-project document counts.

- **Warmup**: `service warmup` reports all 3 models as cached.

- **Encapsulation**: `grep` for `_graph_built_at` returns zero hits
  outside `search.py` internal fallback. No `get_comp()` remains.

- **Lint**: `ruff check` and `ruff format --check` pass on all
  modified files.
