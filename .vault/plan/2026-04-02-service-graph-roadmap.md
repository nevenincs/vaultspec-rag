---
tags:
  - "#plan"
  - "#service-graph"
date: 2026-04-02
related:
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-04-02-service-graph-research]]"
  - "[[2026-04-02-service-graph-phase1-plan]]"
  - "[[2026-04-02-release-readiness-audit]]"
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `service-graph` roadmap

Roadmap for the service orchestration layer (issues #14, #16). Covers
alpha delivery through beta production-readiness. Each milestone maps
to a GitHub issue for tracking.

## Alpha milestones (current PR: feature/service-graph)

### M1: Graph cache unification (ADR D3)

**GitHub:** #14 (Fix graph rebuild race R36-C1)
**Branch:** feature/service-graph
**Scope:**

- Extend `_GraphCache` → public `GraphCache` with TTL + lock
- Add `graph_provider` DI to `VaultSearcher.__init__`
- Concurrent graph build test (N threads at TTL boundary)
- Remove `_graph_built_at` poke from `mcp_server.py`

**Dependencies:** none
**Status:** not started

### M2: ServiceRegistry module (ADR D6)

**GitHub:** #18
**Branch:** feature/service-graph
**Scope:**

- New `service.py` with `ServiceRegistry` class
- Shared `EmbeddingModel` + `dict[Path, ProjectSlot]`
- Per-project `GraphCache`, `VaultStore`, `VaultSearcher`, indexers
- `load_model()`, `get_project()`, `close_all()`, `health()`
- Refactor `api.py` to delegate to registry
- Multi-project isolation tests

**Dependencies:** M1 (graph cache)
**Status:** not started

### M3: FastMCP lifespan + health endpoint (ADR D5 + D2)

**GitHub:** #19
**Branch:** feature/service-graph
**Scope:**

- `service_lifespan` async context manager (eager model loading)
- Starlette app mounting: `/mcp` + `/health`
- `uvicorn.run()` with `timeout_graceful_shutdown=30`
- `stateless_http=True` for multi-agent
- Per-stage startup timing logs in `EmbeddingModel.__init__`
- Refactor MCP tools to accept `project_root` parameter
- Remove old `get_comp()` and `RagComponents`
- Preserve stdio transport path (flag-based, skip Starlette wrapping)
- Health endpoint tests, multi-project MCP tool tests

**Dependencies:** M2 (ServiceRegistry)
**Status:** not started

### M4: Service daemon commands (ADR D1)

**GitHub:** #16 (Service orchestration layer)
**Branch:** feature/service-graph
**Scope:**

- `_spawn_service()` with platform abstraction (Windows/Unix)
- `~/.vaultspec-rag/service.json` status file helpers
- `service start`: TCP port probe, stale recovery, health poll
  with exponential backoff, readiness confirmation
- `service stop`: graceful shutdown via SIGTERM/TerminateProcess
- `service status`: PID liveness + health probe, Rich output
- Start/stop lifecycle tests with ephemeral port

**Dependencies:** M3 (health endpoint)
**Status:** not started

### M5: Model prefetch (ADR D4)

**GitHub:** #20
**Branch:** feature/service-graph
**Scope:**

- `service warmup` command
- `huggingface_hub.snapshot_download()` for 3 model repos
- CUDA check, cache status reporting, timeout defaults
- Tests

**Dependencies:** none (parallel with M4)
**Status:** not started

## Beta milestones (future PRs)

### M6: Rust Windows Service (ADR D7)

**GitHub:** new issue (create when starting beta)
**Scope:**

- Thin Rust binary using `windows-service` crate (Mullvad)
- Spawns/monitors Python uvicorn process
- Auto-start at boot, recovery policies, `services.msc`
- Distribute via maturin `--bindings bin` as separate wheel

**Dependencies:** M4 (daemon commands provide the Python side)
**Status:** deferred to beta

### M7: Granian evaluation (ADR D8)

**GitHub:** new issue (create when starting beta)
**Scope:**

- Evaluate Granian as uvicorn replacement
- Test ASGI compatibility with FastMCP Starlette app
- Benchmark: worker respawn, memory limits, signal handling
- Decision: adopt or keep uvicorn

**Dependencies:** M3 (Starlette app must be stable first)
**Status:** deferred to beta

### M8: Store eviction + log rotation

**GitHub:** new issue (create when starting beta)
**Scope:**

- TTL-based eviction for idle `ProjectSlot` entries
- Log rotation for `~/.vaultspec-rag/service.log`
- Store connection pool limits

**Dependencies:** M2 (ServiceRegistry)
**Status:** deferred to beta

## Execution order (alpha)

```
M1 (graph cache) ──→ M2 (registry) ──→ M3 (lifespan) ──→ M4 (daemon)
                                                      └──→ M5 (warmup)
```

M4 and M5 can run in parallel after M3 completes.

## Issue mapping

| Milestone | GitHub Issue | Status |
|-----------|-------------|--------|
| M1 | #14 | open |
| M2 | #18 | open |
| M3 | #19 | open |
| M4 | #16 | open |
| M5 | #20 | open |
| M6 | deferred | — |
| M7 | deferred | — |
| M8 | deferred | — |
