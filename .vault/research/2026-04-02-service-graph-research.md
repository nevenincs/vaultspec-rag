---
tags:
  - '#research'
  - '#service-graph'
date: 2026-04-02
related:
  - '[[2026-04-02-release-readiness-audit]]'
  - '[[2026-03-09-graph-embedding-round36-audit]]'
  - '[[2026-03-08-fastmcp-lifespan-research]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `service-graph` research: service orchestration layer

Research into the service orchestration architecture for vaultspec-rag,
addressing issues #16 (service layer + startup hangs) and #14 (graph rebuild
race R36-C1). Three strategic options were evaluated: Docker GPU hosting,
Rust-based bollard/cargo orchestration, and Python-native service lifecycle
management.

## Findings

### Q1: Do we need Docker services for GPU model hosting?

**Recommendation: No, not at alpha stage.**

- NVIDIA Container Toolkit works on Windows 11 via Docker Desktop + WSL2
  but adds configuration fragility and measurable overhead via the WSL2
  indirection layer.
- Container cold start would **worsen** the problem: PyTorch+CUDA images are
  10-20GB. Container startup adds image layer extraction on top of model load.
- HuggingFace model caching can be persisted across restarts via volume
  mounts, but this solves re-downloads, not load time.
- Qdrant local mode (`QdrantClient(path=...)`) is explicitly recommended for
  single-user, development, and small-scale use (~20k points). Docker Qdrant
  adds a network hop and configuration overhead with zero benefit at this
  scale.
- Complexity cost for a single-developer alpha tool: Dockerfile +
  docker-compose + GPU passthrough debugging + volume mounts + ~15GB image
  size. Unjustified.
- vaultspec-core is pure Python with no Docker dependency. Adding Docker to
  RAG creates ecosystem divergence.

**Deferral path:** Keep Docker optional for post-1.0 server deployment. A
`compose.yml` can be added later without architectural changes.

### Q2: Should we use Rust bollard/cargo for Docker management?

**Recommendation: Absolutely not.**

- Bollard is a mature Rust crate (v0.19.x) for async Docker Engine API
  bindings. It is designed for Rust-native container orchestration tools, not
  for wrapping around Python projects.
- Cross-language tax is massive: separate build toolchain (cargo + rustc),
  FFI bridging (PyO3/cffi) or subprocess shelling, CI must install Rust,
  developer must maintain two ecosystems.
- Python alternatives exist if programmatic Docker control is ever needed:
  `docker` (docker-py) and `python-on-whales` both provide typed Docker
  Engine API access without leaving the Python ecosystem.
- For 2-3 local services, `docker compose up` in ~30 lines of YAML is
  sufficient. No SDK needed.
- Both vaultspec-core and vaultspec-rag are Python. Introducing Rust for
  the simplest part of the stack (container management) creates
  disproportionate maintenance burden.

### Q3: Python-native service lifecycle management

**Recommendation: MCP HTTP server IS the service layer.**

The infrastructure already exists:

- `mcp_start --port 8766` runs a `streamable-http` server with lazy
  `get_comp()` init (threading.Lock, double-check pattern).
- CLI `--port` fast-path delegates search/index commands to a running MCP
  server via `_try_mcp_search()` and `_try_mcp_reindex()`.
- `service_app` stubs (`start`/`stop`/`status`) are wired in `cli.py` but
  return "not implemented".

**What's missing (estimated ~100 lines of new code):**

- **`service start`**: spawn `mcp start --port` as a detached subprocess.
  On Windows: `creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`.
  On Unix: `start_new_session=True`. Write PID + port to status JSON file
  (e.g., `~/.vaultspec-rag/service.json`).
- **`service stop`**: read status JSON, kill PID, remove file.
- **`service status`**: read status JSON, check PID liveness + HTTP health
  probe.
- **Health endpoint**: FastMCP runs on Starlette/uvicorn, so a `/health`
  route or an MCP tool returning `{"status": "ready", "cuda": true, "models_loaded": true, "qdrant": true, "uptime_s": 42.3}`.
- **Model prefetch**: a `service warmup` command that calls
  `huggingface_hub.snapshot_download()` for all 3 model repos with progress
  bars, before attempting GPU load.

**The 10-minute hang diagnosis:** Most likely caused by first-time model
download, not model loading. Once cached, loading 3 models to GPU takes
~15-30 seconds on RTX 4080. Known issues:

- `SentenceTransformer` and `models.Transformer` can download the same model
  twice if cache paths differ (sentence-transformers #1828).
- A re-download bug can occur when the default cache path changes between
  versions (sentence-transformers #2405).
- HuggingFace CDN can stall without timeout; `HF_HUB_DOWNLOAD_TIMEOUT`
  controls this.

**Optimal startup sequence:**

1. Check CUDA availability -- fail fast
1. Verify model cache (warn if download needed)
1. Load dense model (Qwen3, ~1.2GB VRAM)
1. Load sparse model (SPLADE, ~0.13GB)
1. Load reranker (CrossEncoder, ~0.56GB) -- if enabled
1. Open Qdrant store
1. Warmup query (encode short string, run dummy search)
1. Signal ready (write status file, log timing)

**Path to production:** Replace subprocess spawn with systemd user unit
(Linux) or Windows Service (pywin32) behind the same
`service start/stop/status` interface.

**Reference pattern:** mypy's `dmypy` uses exactly this approach (status
JSON + PID + socket) but relies on `os.fork()` which fails on Windows.
The subprocess approach avoids this by using platform-specific
`creationflags`.

### Q4: Graph rebuild race (R36-C1) within the service layer

**Recommendation: Unify graph ownership, do not wait for service layer.**

Two independent `VaultGraph` caches exist with different strategies:

- `search.py` `VaultSearcher._get_graph()`: TTL-based (300s), **no lock**.
  R36-C1 race: concurrent calls at TTL boundary all construct
  `VaultGraph(root_dir)` in parallel.
- `api.py` `_GraphCache`: `threading.Lock` + double-check, explicit
  invalidation via `invalidate()`, no TTL. Used by `get_related()`.
- `mcp_server.py` reaches into `comp.searcher._graph_built_at = 0.0` to
  force rebuild after reindex -- fragile, breaks encapsulation.

**Fix:** Unify into a single `_GraphCache` instance (the `api.py` pattern,
extended with optional TTL). `VaultSearcher.__init__` accepts a
`graph_provider: Callable[[], VaultGraph | None]` instead of managing its
own cache. This:

- Fixes R36-C1 (lock already exists in `_GraphCache`)
- Eliminates the duplicate cache
- Replaces fragile `_graph_built_at = 0.0` poke with
  `_graph_cache.invalidate()`
- Requires no new service layer -- just dependency injection of the graph
  provider
- Keeps TTL behavior by adding it to `_GraphCache.get()` (check
  `time.monotonic()` inside the lock)

## Evaluated approaches summary

| Approach                      | Verdict                    | Rationale                                             |
| ----------------------------- | -------------------------- | ----------------------------------------------------- |
| Docker GPU services           | Defer to post-1.0          | Complexity unjustified for alpha; worsens cold start  |
| Rust bollard/cargo            | Reject                     | Cross-language tax, over-engineering for 2-3 services |
| Python subprocess daemon      | **Adopt for alpha**        | ~100 LOC, zero dependencies, cross-platform           |
| MCP HTTP server as service    | **Adopt (already exists)** | Infrastructure in place, just needs service wrappers  |
| systemd / Windows Service     | Defer to beta              | Correct for production, too heavy for alpha           |
| Process managers (supervisor) | Skip                       | External dependency for single-process service        |
| Unified graph cache           | **Adopt immediately**      | Fixes R36-C1, eliminates duplicate cache, clean DI    |

## Open questions for ADR

1. **Default port**: should `service start` use a well-known port (e.g.,
   8766\) or require explicit `--port`?
1. **Auto-start**: should CLI commands auto-start the service if not running,
   or require explicit `service start`?
1. **Status file location**: `~/.vaultspec-rag/service.json` (global) or
   `{project}/.qdrant/service.json` (per-project)?
1. **Health endpoint**: MCP tool (`get_health`) vs raw HTTP route (`/health`)?
1. **Model prefetch**: separate `service warmup` command or integrated into
   `service start`?

## Addendum: Multi-consumer and state management (2026-04-02)

A second round of research was conducted after the initial findings were
deemed insufficient for multi-consumer scenarios. The original research
framed the problem as "how to daemonize a subprocess" when the actual
problem is "how to serve GPU models to multiple concurrent consumers."

### Q5: ML model serving frameworks

**Recommendation: do not add any serving framework.**

TorchServe, Ray Serve, BentoML, and Triton are designed for multi-model,
multi-GPU, cloud-scale deployments. They add massive dependency trees
(Ray alone ~200MB), cluster management, and containerization assumptions.
For a single-GPU local tool with 3 small models (~1.9GB total), they are
categorically wrong.

The current architecture is already the industry-correct pattern for this
scale: single uvicorn process (via FastMCP), `threading.Lock` for lazy
init, `asyncio.Semaphore(1)` for GPU exclusion, `anyio.to_thread.run_sync`
bridging sync inference into async handlers.

### Q6: Service discovery (dmypy pattern)

**Recommendation: adopt the dmypy pattern.**

mypy's `dmypy` implements the gold-standard pattern for local tool daemons:
status file (`.dmypy.json`) containing `{pid, port}`, client reads file
then checks PID + socket. On Windows, TCP localhost replaces Unix domain
sockets. This pattern is proven by mypy, ruff, and language servers.

For vaultspec-rag: status file at a well-known path containing
`{pid, port}`. CLI checks: file exists, PID alive, HTTP health responds.
If all pass, reuse; otherwise, start fresh.

### Q7: Singleton guarantee

**Recommendation: TCP port binding as the lock.**

If `bind("127.0.0.1", 8766)` fails with `EADDRINUSE`, the service is
already running. Port binding is self-cleaning: OS releases the port when
the process dies. No stale PID file races. This is superior to file locks
(`fcntl.flock` differs across Unix/Windows) and PID files (require liveness
checks prone to TOCTOU races).

### Q8: Per-project vs global service

**Recommendation: one global service, multi-project routing.**

GPU models are project-independent (same Qwen3/SPLADE/CrossEncoder for
all projects). Only Qdrant data varies per project. The service should
hold one `EmbeddingModel` singleton and a `dict[Path, VaultStore]` mapping
project roots to their Qdrant connections. MCP tools accept an optional
`project_root` parameter. This is the standard multi-tenant pattern:
shared compute, isolated storage.

The current `mcp_server.py` hardcodes `VAULTSPEC_ROOT` into a single
`RagComponents` instance. The `api.py` `get_engine()` already handles
root-dir switching with lock + close-old-store, but as a serial singleton
rather than a concurrent dict.

### Q9: Session management and FastMCP

FastMCP creates a session per HTTP connection. All sessions share the same
process and therefore the same model singleton. `stateless_http=True` is
recommended for multi-agent use (no session affinity required -- each
request is independent). The existing `_gpu_sem = asyncio.Semaphore(1)`
serializes GPU work across sessions correctly.

GPU OOM from one consumer does NOT crash the process (PyTorch catches it).
The `_MAX_QUERY_LEN` cap and `_clamp_top_k` bound per-request memory.
Qdrant local mode handles concurrent reads safely with internal locking.

### Q10: Readiness signaling

A single health endpoint (`GET /health` or MCP tool) returning
`{"status": "ready", "models_loaded": true}` suffices for local tools.
No need for separate `/healthz` and `/readyz` (Kubernetes conventions).
CLI polls with exponential backoff (100ms, 200ms, 400ms... up to 5s).

### Q11: Graceful shutdown

Uvicorn handles SIGTERM natively: stops accepting connections, waits for
in-flight requests, honors `--timeout-graceful-shutdown`. The existing
`_watcher_stop` event and watcher task cleanup are in place. Set a
reasonable drain timeout (30s) so long reindexing doesn't block shutdown.

### Q12: Windows process lifecycle

`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` is preferred over
`DETACHED_PROCESS` in Python 3.7+. The spawned process writes a status
file; the client polls it. There is no `fork()` on Windows, so the
dmypy pattern (status file + TCP port) works cross-platform without
modification.

### Updated evaluated approaches summary

| Approach                               | Verdict               | Rationale                                 |
| -------------------------------------- | --------------------- | ----------------------------------------- |
| TorchServe / Ray Serve / BentoML       | Reject                | Overkill for single-GPU local tool        |
| HF TEI (Rust embedding server)         | Learn from, don't use | Architecture insights, wrong dependency   |
| gRPC transport                         | Skip                  | HTTP overhead negligible at this scale    |
| Per-project service instances          | Reject                | GPU models are shared; only Qdrant varies |
| Global service + multi-project routing | **Adopt**             | Shared compute, isolated storage          |
| dmypy-style service discovery          | **Adopt**             | Proven by mypy/ruff/LSP, cross-platform   |
| TCP port binding as singleton          | **Adopt**             | Self-cleaning, no stale file races        |
| `stateless_http=True`                  | **Adopt**             | No session affinity for multi-agent       |
| `CREATE_NO_WINDOW` on Windows          | **Adopt**             | Preferred over DETACHED_PROCESS           |

## Addendum: Implementation layer research (2026-04-02)

A third research round addressed the implementation strategy: FastMCP
lifecycle hooks, Rust service supervisors, the `_Engine` kernel question,
and alternative ASGI servers.

### Q13: FastMCP lifespan replaces external service management

FastMCP accepts a `lifespan` async context manager that runs startup code
before accepting connections and cleanup code on shutdown. Combined with
Starlette route mounting, this gives:

- Eager GPU model loading in lifespan startup (before accepting requests)
- Raw `GET /health` endpoint via `Route("/health", handler)` alongside
  `Mount("/mcp", app=mcp.streamable_http_app())`
- Graceful shutdown via `uvicorn.run(timeout_graceful_shutdown=30)`
- Full uvicorn config control without reaching into FastMCP internals

The pattern:

```python
app = Starlette(
    routes=[Mount("/mcp", app=mcp.streamable_http_app()),
            Route("/health", health_handler)],
    lifespan=combined_lifespan,
)
uvicorn.run(app, host="127.0.0.1", port=8766,
            timeout_graceful_shutdown=30)
```

The `/health` endpoint becomes available only after lifespan completes --
this is the natural readiness signal. The CLI spawns uvicorn, polls
`GET /health` with exponential backoff until 200.

The previous Task #25 conclusion ("lazy-init strictly better than
lifespan") was correct for stdio transport where startup delays the
client. For a persistent HTTP service, eager loading via lifespan is
strictly better -- the service should not accept requests until warm.

### Q14: ServiceRegistry as new `service.py` module

Neither `_Engine` (serial singleton, closes old store on root-dir switch)
nor `RagComponents` (single-project) should become the multi-project
kernel. Both use serial singleton lock patterns incompatible with
concurrent stores.

Recommendation: new `service.py` with `ServiceRegistry`:

- `EmbeddingModel` (shared, loaded once in lifespan)
- `dict[Path, ProjectSlot]` (per-project VaultStore + VaultSearcher +
  indexers + GraphCache)
- Per-key locking via `threading.Lock` per `ProjectSlot`
- `register/get/close` semantics with TTL-based eviction (deferred)
- `api.py` becomes thin single-project facade delegating to registry
- `mcp_server.py` calls registry directly for multi-project dispatch
- Both existing lock patterns (`_engine_lock`, `_comp_lock`) collapse
  into the registry's internal locking

### Q15: Rust service supervisor -- deferred to beta

No established "Rust supervisor for Python" pattern exists in production.
The only compelling justification is Windows Service registration via
the `windows-service` crate (Mullvad VPN, 2.8M downloads, production-
grade). This gives auto-start at boot, recovery policies, and
`services.msc` visibility -- capabilities Python cannot provide natively.

Distribution: maturin `--bindings bin` packages a standalone Rust binary
as a Python wheel entry point. No `cargo install` prerequisite.

Other Rust tools evaluated:

- `watchexec-supervisor`: Job API modeled after systemctl, but niche
- `systemfd`: socket-passing for zero-downtime restarts; uvicorn doesn't
  support LISTEN_FDS, dead end
- `pueue`: task queue, not service supervisor
- `supervisor-rs`: low adoption

### Q16: Granian (Rust ASGI server) -- evaluate at beta

Granian is a Rust-core ASGI server with built-in worker respawn, RSS-based
memory limits, and signal handling. Its free-threaded mode (v2.0+) shares
GPU models across workers in a single process without custom singleton
machinery.

Does not solve CLI service commands (start/stop/status) -- those remain
application-level regardless of ASGI server. Worth evaluating as a
uvicorn replacement at beta if real lifecycle management gaps emerge.

### Q17: Python alternatives ruled out

- `multiprocessing.managers`: CUDA contexts are process-local, GPU
  tensors cannot cross process boundaries
- `python-daemon`: Unix-only, no Windows support
- `circus` (Mozilla): effectively abandoned (frozen at 0.17.2)
- Robyn: not ASGI-compatible (custom Rust runtime)
- Hypercorn: viable ASGI server but no process supervision advantage

### Final architecture layers

| Layer                   | Technology                                             | Status           |
| ----------------------- | ------------------------------------------------------ | ---------------- |
| 1. ASGI server          | uvicorn + FastMCP lifespan + Starlette mount           | Alpha            |
| 2. State management     | `ServiceRegistry` in new `service.py`                  | Alpha            |
| 3. CLI service commands | dmypy pattern (subprocess + status file + health poll) | Alpha            |
| 4. Windows Service      | Rust binary via `windows-service` crate + maturin      | Beta             |
| 5. ASGI server upgrade  | Granian (Rust ASGI with supervisor)                    | Evaluate at beta |
