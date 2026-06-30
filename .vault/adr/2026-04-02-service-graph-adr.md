---
tags:
  - '#adr'
  - '#service-graph'
date: 2026-04-02
modified: '2026-06-30'
related:
  - '[[2026-04-02-service-graph-research]]'
  - '[[2026-04-02-release-readiness-audit]]'
  - '[[2026-03-09-graph-embedding-round36-audit]]'
---

# `service-graph` adr: service orchestration layer | (**status:** `accepted`)

## Problem Statement

vaultspec-rag has no service layer. Three GPU models (~1.9GB VRAM) are
loaded inline by every entry point (CLI, MCP server, API facade) on every
cold start. This creates:

- 10+ minute startup hangs when models are not cached locally
- ~15-30 second GPU load on every CLI invocation even when cached
- A graph rebuild race condition (R36-C1) where concurrent searches at TTL
  boundary trigger parallel `VaultGraph` constructions
- Two independent graph caches (`search.py` unlocked TTL,
  `api.py` locked explicit-invalidation) with fragile cross-module coupling
  (`mcp_server.py` pokes `searcher._graph_built_at = 0.0`)

The library code conflates service lifecycle (boot, ready, shutdown) with
domain logic (search, index). Every consumer re-initializes the full stack.

## Considerations

**Evaluated and rejected:**

- **Docker GPU services**: NVIDIA Container Toolkit on Windows 11 / WSL2 is
  functional but adds configuration fragility, 10-20GB image overhead, and
  worsens cold start. Qdrant local mode is correct at this scale. Ecosystem
  divergence from vaultspec-core (pure Python). Deferred to post-1.0.

- **Rust bollard/cargo**: Cross-language tax (separate toolchain, FFI
  bridging, CI complexity) is unjustified. Python docker SDK or
  `docker compose up` are sufficient if Docker is ever needed. Rejected.

- **Process managers (supervisor, circus, PM2)**: External dependency for a
  single-process service. Not justified.

- **systemd / Windows Service**: Correct for production but too heavy for
  alpha. Deferred to beta.

**Adopted:**

- **Global resident service (dmypy pattern)**: one process, shared GPU
  models, multi-project routing via `ServiceRegistry`. The MCP HTTP
  server IS the service, wrapped by `service start/stop/status` CLI
  commands using subprocess + TCP port binding as singleton lock.

- **FastMCP lifespan + Starlette mounting**: eager model loading before
  accepting connections, raw `/health` endpoint for readiness, uvicorn
  graceful shutdown with drain timeout.

- **`ServiceRegistry` in new `service.py`**: centralized state management
  with shared `EmbeddingModel` + `dict[Path, ProjectSlot]` for per-project
  isolation. Replaces both `_Engine` and `RagComponents` as the state
  kernel.

- **Unified graph cache with dependency injection**: merge two caches into
  one `GraphCache` with lock + TTL, inject into `VaultSearcher` per
  project. Fixes R36-C1.

- **Model prefetch**: separate download step to diagnose and eliminate the
  10-minute hang.

## Constraints

- Windows 11 primary platform, cross-platform desirable (Linux/macOS)
- GPU always available (RTX 4080, 16GB VRAM) -- no CPU fallback
- No new runtime dependencies beyond what's already in `pyproject.toml`
- Must not break existing MCP stdio transport (Claude Desktop uses it)
- Must not break existing test infrastructure (session-scoped fixtures)
- vaultspec-core alignment: pure Python, no Docker requirement

## Implementation

### D1: Global resident service (dmypy pattern)

The existing `mcp start --port` command becomes a global resident service
shared by all consumers (multiple Claude agents, CLI invocations, different
projects). This follows the dmypy pattern proven by mypy, ruff, and
language servers.

**Architecture: one process, shared models, isolated storage.**

- One `EmbeddingModel` singleton (~1.9GB VRAM) serves all consumers.
- A `dict[Path, VaultStore]` maps resolved project roots to their Qdrant
  connections. Stores are opened lazily on first request for a project and
  kept alive for the service lifetime.
- MCP tools accept an optional `project_root` parameter (defaults to
  `VAULTSPEC_ROOT` or CWD). The service resolves it and routes to the
  correct `VaultStore`.

**Singleton guarantee: TCP port binding.**

- If `bind("127.0.0.1", 8766)` fails with `EADDRINUSE`, the service is
  already running. Port binding is self-cleaning: OS releases the port
  when the process dies. No stale PID file races.
- A status file at `~/.vaultspec-rag/service.json` records
  `{pid, port, started_at}` as a secondary discovery mechanism. The port
  bind is authoritative; the status file is advisory.

**`service start [--port PORT]`**:

- Default port: **8766** (configurable via `--port` or
  `VAULTSPEC_RAG_PORT` env var).
- Spawn via `_spawn_service()` helper encapsulating platform differences:
  - Windows: `subprocess.Popen(cmd, creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW, stdin=DEVNULL, stdout=log_file, stderr=STDOUT)`
  - Unix: `subprocess.Popen(cmd, start_new_session=True, stdin=DEVNULL, stdout=log_file, stderr=STDOUT)`
- Write status to `~/.vaultspec-rag/service.json` (global, not
  per-project -- the service is shared across projects).
- Log file at `~/.vaultspec-rag/service.log` (append mode). Log rotation
  deferred to beta.
- **Stale status recovery**: before spawning, check status file. If PID is
  dead, reclaim. If PID is alive, probe health. If healthy, report
  "already running." If unhealthy (port bound but not responding), report
  error with diagnostic hint.
- **Port conflict handling**: if the spawned process exits immediately
  (port in use by non-service process), report a clear message.
- Poll health endpoint with exponential backoff (100ms, 200ms, 400ms...
  up to 30s timeout).
- Print readiness confirmation with startup timing.

**`service stop`**:

- Read status file, verify PID, send SIGTERM (Unix) or
  `TerminateProcess` (Windows), remove status file.
- Uvicorn handles graceful shutdown natively: stops accepting connections,
  drains in-flight requests, honors `--timeout-graceful-shutdown 30`.

**`service status`**:

- Read status file, check PID liveness, probe HTTP health endpoint.
- Report: running/stopped, uptime, port, GPU, model status, connected
  projects (keys of the `VaultStore` dict), document counts per project.

**Auto-start: no.** CLI commands that use `--port` attempt to connect and
fall back to in-process execution when the server is unavailable. This
existing behavior is preserved. Explicit `service start` is simpler to
reason about and debug.

**FastMCP transport**: use `stateless_http=True` so each request is
independent with no session affinity. Multi-agent consumers (multiple
Claude instances) do not need sticky sessions.

### D2: Health endpoint

Implement as a **raw HTTP `GET /health` route** mounted alongside the MCP
server on the same Starlette app (see D5). This is simpler and more
standard than an MCP tool for health polling:

- Standard HTTP GET is universally understood by monitoring tools, load
  balancers, and CLI health checks. No MCP client protocol needed.
- The CLI `service start` and `service status` commands poll
  `GET http://127.0.0.1:{port}/health` directly -- simpler than
  establishing an MCP session just to check liveness.
- The endpoint returns JSON:
  `{"status": "ready"|"loading"|"error", "cuda": bool, "models_loaded": bool, "projects": [...], "uptime_s": float}`.
- Available only after FastMCP lifespan startup completes -- serves as
  the natural readiness signal.

### D3: Unified graph cache

Merge the two graph caching mechanisms into a single `GraphCache` class:

- **Location**: `api.py` (where the current `_GraphCache` lives).
- **Interface**: `get(root_dir) -> VaultGraph | None` and `invalidate()`.
- **Locking**: `threading.Lock` with double-check pattern (existing).
- **TTL**: add `time.monotonic()` check inside the lock. Default 300s
  from config (`graph_ttl_seconds`). The lock prevents concurrent rebuilds
  at TTL boundary (fixes R36-C1).
- **Dependency injection**: `VaultSearcher.__init__` accepts a
  `graph_provider: Callable[[], VaultGraph | None]` parameter (zero-arg
  callable -- the caller binds `root_dir` via closure, e.g.,
  `lambda: graph_cache.get(root_dir)`). When provided, `_get_graph()`
  delegates entirely to `graph_provider` and the internal
  `_cached_graph` / `_graph_built_at` fields are unused. When `None`
  (backward compat for tests and CLI ad-hoc callers), falls back to an
  internal cache with the same lock+TTL behavior.
- **Mandatory adoption point**: `ServiceRegistry.get_project()` (D6)
  MUST wire `graph_provider` from the per-project `GraphCache` instance.
  This is where R36-C1 manifests (concurrent MCP tool calls). CLI callers
  (`cli.py` ad-hoc `VaultSearcher` construction) are single-threaded and
  exempt -- they use the internal fallback cache safely.
- **Invalidation**: `graph_cache.invalidate()` replaces the fragile
  `searcher._graph_built_at = 0.0` poke in `mcp_server.py`.
- **Per-project instances**: each `ProjectSlot` in the `ServiceRegistry`
  (D6) creates its own `GraphCache` bound to that project's root_dir.
  Different projects have different `.vault/` directories and therefore
  different graph structures.

### D4: Model prefetch

Add a **`service warmup`** command (separate from `service start`):

- Calls `huggingface_hub.snapshot_download()` for all 3 model repos
  (Qwen3-Embedding-0.6B, splade-v3, bge-reranker-v2-m3) with progress
  bars.
- Verifies CUDA availability first (fail fast).
- Sets `HF_HUB_DOWNLOAD_TIMEOUT=60` if not already set.
- Reports cache status per model (cached/downloading/failed).
- Does NOT load models to GPU -- that happens on `service start`.

Rationale: separating download from GPU load lets users diagnose network
vs. GPU issues independently. `service start` benefits because models are
pre-cached.

### D5: FastMCP lifespan + Starlette mounting

Replace the current `mcp.run()` call with an explicit Starlette app that
mounts the MCP server alongside a raw health endpoint:

```
app = Starlette(
    routes=[Mount("/mcp", app=mcp.streamable_http_app()),
            Route("/health", health_handler)],
    lifespan=service_lifespan,
)
uvicorn.run(app, host="127.0.0.1", port=port,
            timeout_graceful_shutdown=30)
```

The `service_lifespan` async context manager:

- **Startup**: check CUDA, log HF cache status, load dense model
  (log time), load sparse model (log time), load reranker (log time,
  skip if disabled), log total. Models load eagerly BEFORE accepting
  connections. Consumers never hit a cold model load.
- **Yield**: service is ready, `/health` returns 200.
- **Shutdown (finally)**: close all project stores, release GPU memory,
  stop filesystem watchers.

The `/health` endpoint returns JSON:
`{"status": "ready"|"loading"|"error", "cuda": bool, "models_loaded": bool, "projects": [...], "uptime_s": float}`.

This endpoint becomes available only after lifespan startup completes --
the natural readiness signal. The CLI polls `GET /health` with
exponential backoff (100ms, 200ms, 400ms... up to 30s).

The previous Task #25 conclusion ("lazy-init strictly better than
lifespan") was correct for stdio transport. For a persistent HTTP
service, eager loading via lifespan is strictly better.

### D6: ServiceRegistry in new `service.py` module

Neither `_Engine` (serial singleton, closes old store on root-dir switch)
nor `RagComponents` (single-project) should become the multi-project
kernel. A new `service.py` module owns the centralized state:

**`ServiceRegistry` class:**

- `_model: EmbeddingModel | None` -- shared GPU models (loaded once in
  lifespan, referenced by all projects).
- `_projects: dict[Path, ProjectSlot]` -- per-project components, each
  containing `VaultStore`, `VaultSearcher`, `VaultIndexer`,
  `CodebaseIndexer`, and `GraphCache`.
- `_lock: threading.Lock` -- guards `_projects` dict mutations.
- Per-`ProjectSlot` locking: each slot has its own lock for operations
  that mutate project-local state (reindex, graph rebuild).

**Methods:**

- `load_model()` -- eager model loading (called from lifespan).
- `get_project(root: Path) -> ProjectSlot` -- lazy per-project init.
  Creates VaultStore + VaultSearcher (with `graph_provider` from
  per-project `GraphCache`) + indexers on first access. Reuses shared
  model.
- `close_project(root: Path)` -- close Qdrant store, remove from dict.
- `close_all()` -- shutdown (called from lifespan finally).
- `health() -> dict` -- aggregated health status.

**Consumers:**

- `mcp_server.py` calls `registry.get_project(root)` in each MCP tool,
  passing `project_root` parameter from the request.
- `api.py` becomes a thin single-project facade: `get_engine()` calls
  `registry.get_project()` internally. Public API unchanged.
- MCP tools gain an optional `project_root: str | None` parameter.
  Default: `VAULTSPEC_ROOT` env var or CWD at service startup.

**Store cleanup:** deferred to beta. Alpha uses manual `service stop` +
restart to clear all stores. No unbounded accumulation risk at alpha
scale (single developer, 1-3 projects).

### D7: Deferred -- Rust Windows Service (beta)

A thin Rust binary using the `windows-service` crate (Mullvad, 2.8M
downloads) that spawns/monitors the Python uvicorn process. Provides
auto-start at boot, recovery policies, `services.msc` visibility.
Distributed via maturin `--bindings bin` as a separate wheel.

Not needed for alpha. The subprocess + PID file approach is sufficient
for manual `service start/stop`.

### D8: Deferred -- Granian ASGI server (evaluate at beta)

Granian is a Rust-core ASGI server with built-in worker respawn,
RSS-based memory limits, and signal handling. Its free-threaded mode
shares GPU models across workers naturally. Worth evaluating as a
uvicorn replacement if real lifecycle management gaps emerge. Does not
change the architectural decisions above -- drop-in replacement for
`uvicorn.run()`.

## Rationale

- **MCP-as-service**: zero new infrastructure. The server process already
  owns GPU resources, has thread-safe lazy init, GPU semaphore, and
  filesystem watcher. The dmypy-style service discovery (status file +
  TCP port binding as singleton lock) is proven by mypy, ruff, and
  language servers.

- **Global service, not per-project**: GPU models are project-independent
  (~1.9GB VRAM regardless of which project is being searched). Running
  separate service instances per project would waste VRAM and violate the
  single-GPU constraint. The multi-tenant pattern (shared compute,
  isolated storage) is standard in inference serving.

- **TCP port binding as singleton**: self-cleaning (OS releases port on
  crash), no stale PID file races, works identically on Windows and Unix.
  The status file is advisory for CLI discovery, not authoritative for
  locking.

- **`stateless_http=True`**: multiple Claude agents connecting
  concurrently do not need session affinity. Each MCP request is
  self-contained. The existing `_gpu_sem` serializes GPU work correctly.

- **No auto-start**: explicit is better than implicit. Auto-start hides
  failures and makes debugging harder. The existing fallback (in-process
  execution when `--port` server is unavailable) is preserved.

- **Raw HTTP `/health` over MCP tool**: standard HTTP GET is universally
  understood, doesn't require establishing an MCP session to check
  liveness, and naturally gates on lifespan completion. Simpler for CLI
  polling and future monitoring integration.

- **Unified graph cache**: eliminates a class of bugs (duplicate caches,
  fragile internal pokes, unlocked concurrent rebuilds) with a clean DI
  pattern that doesn't require architectural changes.

- **Separate warmup command**: model download is a network operation that
  can fail independently of GPU operations. Separating them gives users
  clear diagnostics.

- **No serving frameworks**: TorchServe, Ray Serve, BentoML, and Triton
  are designed for cloud-scale multi-GPU deployments. They add massive
  dependency trees and complexity without benefit for a single-GPU local
  tool. The existing uvicorn + threading.Lock + asyncio.Semaphore
  architecture is the industry-correct pattern for this scale.

- **`ServiceRegistry` as new module**: `_Engine` and `RagComponents`
  are both serial singletons (close-old-on-switch) incompatible with
  concurrent multi-project stores. A dedicated `service.py` isolates
  multi-project complexity with per-key locking, keeping both `api.py`
  and `mcp_server.py` as thin consumers. Both existing lock patterns
  collapse into the registry's internal locking.

- **FastMCP lifespan for eager loading**: the lifespan context manager
  runs model loading before accepting connections. Combined with
  Starlette route mounting, this gives a raw `/health` endpoint
  that naturally signals readiness (available only after lifespan
  completes). No external readiness signaling mechanism needed.

- **Rust deferred, not rejected**: the `windows-service` crate is
  production-grade and solves a real gap (auto-start, recovery
  policies, services.msc). But it adds a build toolchain and is
  unnecessary for alpha. Granian (Rust ASGI server) is similarly
  worth evaluating later. Both can be adopted without architectural
  changes.

## Consequences

- **CLI behavior change**: `service start/stop/status` commands become
  functional (currently stubs). No breaking changes to other commands.

- **`mcp_server.py` restructure**: the single `RagComponents` dataclass
  is replaced by a split architecture (shared model + per-project stores).
  This is the largest change and must be carefully tested.

- **`VaultSearcher` constructor change**: new optional `graph_provider`
  parameter. Existing callers (tests, CLI ad-hoc construction) continue to
  work with default `None` (internal cache with lock+TTL).

- **`mcp_server.py` cleanup**: `comp.searcher._graph_built_at = 0.0` poke
  replaced by `_graph_cache.invalidate()`. Cleaner encapsulation.

- **MCP tool signature change**: all tools gain optional `project_root`
  parameter. Backward compatible (defaults to env var / CWD).

- **New files**: one new module `service.py` (ServiceRegistry). All
  other changes are to existing modules (`cli.py`, `api.py`, `search.py`,
  `mcp_server.py`, `embeddings.py`).

- **New dependency**: none. `subprocess`, `os`, `signal`, `json`,
  `time` are stdlib.

- **Multi-consumer support**: multiple Claude agents, CLI sessions, and
  API consumers share GPU models via the same service. No model
  duplication across consumers.

- **Docker deferral**: Docker support is not blocked -- a `compose.yml`
  can be added later wrapping the same global service. The subprocess
  daemon can coexist with or be replaced by Docker.

- **Test impact**: existing session-scoped fixtures continue to work.
  New tests needed for: `service start/stop/status` (subprocess
  management), `GraphCache` with TTL + lock (concurrent access),
  `get_health` tool, multi-project routing (two project roots sharing
  one model), `service warmup` (model cache verification). Service
  daemon tests should use `_spawn_service()` helper for platform
  abstraction, short health-poll timeouts (5s), and ephemeral ports.

- **Deferred concerns**: log rotation for `service.log` (beta). systemd /
  Windows Service integration (beta). Docker `compose.yml` (post-1.0).
  Store idle timeout / eviction (can start with no eviction at alpha --
  manual `service stop` + restart clears all stores).
