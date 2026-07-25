---
tags:
  - '#plan'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-07-25'
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-04-02-service-graph-research]]'
  - '[[2026-04-02-service-graph-phase1-plan]]'
  - '[[2026-04-02-release-readiness-audit]]'
---

# `service-graph` roadmap

Roadmap for the service orchestration layer (issues #14, #16). Covers
alpha delivery through beta production-readiness. Each milestone maps
to a GitHub issue for tracking.

### Phase `P01` - Alpha milestones

The orchestration layer as originally scoped: one owned graph cache, the multi-project registry, an eager-loading lifespan behind a health endpoint, the daemon control verbs, and the warmup path.

- [x] `P01.S01` - Unify graph ownership behind one cache carrying a time-to-live and a lock, closing the concurrent-rebuild race; `src/vaultspec_rag/graph_cache.py`.
- [x] `P01.S02` - Introduce the multi-project registry owning one shared embedding model and a per-project slot for every derived resource; `src/vaultspec_rag/service.py`.
- [x] `P01.S03` - Load the model eagerly during the server lifespan and expose readiness through a health endpoint; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P01.S04` - Deliver the daemon control verbs over a status file recording port and process identity; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P01.S05` - Deliver the warmup path reporting device availability and model cache state ahead of first use; `src/vaultspec_rag/cli/_service_start.py`.

### Phase `P02` - Pre-beta hardening milestones

The four hardening milestones raised against the alpha layer: search throughput under the device semaphore, per-project watching, real-subprocess lifecycle coverage, and the boundary and disclosure fixes.

- [x] `P02.S06` - Narrow the device semaphore to the compute section so concurrent searches are no longer serialised by work that does not touch the device; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S07` - Give each resident project its own filesystem watcher so a change in one root cannot reindex another; `src/vaultspec_rag/watcher.py`.
- [x] `P02.S08` - Cover the daemon lifecycle against real subprocesses rather than in-process doubles; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.
- [x] `P02.S09` - Validate the project boundary on root resolution and reduce disclosure on the health and status surfaces; `src/vaultspec_rag/server/_utils.py`.

### Phase `P03` - Beta milestone

The one deferred beta milestone that was subsequently delivered: bounded project slots with a rotated daemon log.

- [x] `P03.S10` - Bound the resident project slots by ceiling and idle age, and rotate the daemon log rather than appending without limit; `src/vaultspec_rag/service.py`.

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
**Status:** complete (PR #21)

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
**Status:** complete (PR #21)

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
**Status:** complete (PR #21)

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
**Status:** complete (PR #21)

### M5: Model prefetch (ADR D4)

**GitHub:** #20
**Branch:** feature/service-graph
**Scope:**

- `service warmup` command
- `huggingface_hub.snapshot_download()` for 3 model repos
- CUDA check, cache status reporting, timeout defaults
- Tests

**Dependencies:** none (parallel with M4)
**Status:** complete (PR #21)

## Post-merge follow-ups (from audit)

### M5.1: Performance — narrow \_gpu_sem scope

**GitHub:** #22
**Scope:** Narrow semaphore to GPU-only operations, share CrossEncoder
**Dependencies:** M3 (lifespan)
**Status:** open

### M5.2: Multi-project filesystem watcher

**GitHub:** #23
**Scope:** dict[Path, asyncio.Task] per-project watcher tracking
**Dependencies:** M2 (ServiceRegistry)
**Status:** open

### M5.3: Service lifecycle integration tests

**GitHub:** #24
**Scope:** Real GPU subprocess start/stop/status tests
**Dependencies:** M4 (daemon commands)
**Status:** open

### M5.4: Security hardening

**GitHub:** #25
**Scope:** project_root allowlist, .ragignore, health auth
**Dependencies:** M3 (lifespan)
**Status:** open

## Beta milestones (future PRs)

### M6: Rust Windows Service (ADR D7)

**GitHub:** new issue (create when starting beta)
**Scope:**

- Thin Rust binary using `windows-service` crate (Mullvad)
- Spawns/monitors Python uvicorn process
- Auto-start at boot, recovery policies, `services.msc`
- Distribute via maturin `--bindings bin` as separate wheel

**Dependencies:** M4 (daemon commands provide the Python side)
**Status:** not pursued. The service acquired its own supervision, quiesce and
orphan-reaping behaviour in Python instead, so a separate native service wrapper
was never revisited. No issue tracks it.

### M7: Granian evaluation (ADR D8)

**GitHub:** new issue (create when starting beta)
**Scope:**

- Evaluate Granian as uvicorn replacement
- Test ASGI compatibility with FastMCP Starlette app
- Benchmark: worker respawn, memory limits, signal handling
- Decision: adopt or keep uvicorn

**Status:** not pursued. The existing server was retained and hardened rather
than replaced, so the evaluation was never run. No issue tracks it.

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

| Milestone | GitHub Issue | Status           |
| --------- | ------------ | ---------------- |
| M1        | #14          | complete         |
| M2        | #18          | complete         |
| M3        | #19          | complete         |
| M4        | #16          | complete         |
| M5        | #20          | complete         |
| M5.1      | #22          | open (follow-up) |
| M5.2      | #23          | open (follow-up) |
| M5.3      | #24          | open (follow-up) |
| M5.4      | #25          | open (follow-up) |
| M6        | deferred     | —                |
| M7        | deferred     | —                |
| M8        | deferred     | —                |

## Description

See the summary above.

## Steps
