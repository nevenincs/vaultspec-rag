---
tags:
  - "#audit"
  - "#service-graph"
date: 2026-04-02
related:
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-04-02-service-graph-phase1-plan]]"
  - "[[2026-04-02-service-graph-research]]"
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `service-graph` Code Review

Rolling audit log for the service orchestration implementation.
3 parallel reviewers covering 5 phases. 252 unit tests passing.

## Phase 1: GraphCache unification

### PHASE1-001 | MEDIUM | GraphCache.get() TTL=0 allows repeated rebuilds

When `ttl_seconds=0.0` the `>=` comparison in `_is_stale()` means the
cache is always stale, even immediately after rebuild inside the lock.
The concurrency test uses TTL=0 but only checks all threads got a
non-None result — it does not verify that exactly one `VaultGraph`
construction occurred. The R36-C1 fix IS correct (lock prevents
concurrent builds) but the test doesn't prove it rigorously.

**File:** `api.py:317`, `test_graph_cache.py:106`
**Fix:** Add a construction counter to verify exactly 1 build under
concurrent access.

### PHASE1-002 | LOW | Tautological assertion in test_get_returns_none

`assert result is None or result is not None` is always true. The test
only checks "does not crash."

**File:** `test_graph_cache.py:70`

### PHASE1-003 | LOW | GraphCache failure sets _built_at, suppressing retries

After a failed `VaultGraph` construction, `_built_at` is set to
`time.monotonic()`. No retry for `ttl_seconds` (300s default). If
failure was transient (e.g., `.vault/` briefly missing during git),
user gets None for 5 minutes.

**File:** `api.py:344`

### PHASE1-004 | INFO | Module-level _graph_cache in api.py is unused

`_graph_cache = GraphCache()` at line 360 is dead code. Each `_Engine`
creates its own instance.

**File:** `api.py:360`

## Phase 2: ServiceRegistry

### PHASE2-001 | HIGH | ServiceRegistry.load_model() is not thread-safe

`load_model()` checks `if self._model is not None: return` without
holding a lock. Two concurrent calls can both pass the check and
create two `EmbeddingModel` instances (~1.9GB VRAM each), with one
silently discarded.

**File:** `service.py:68-80`
**Fix:** Add double-check lock pattern, consistent with `get_project()`.

### PHASE2-002 | MEDIUM | close_all() sets_model = None outside the lock

`self._model = None` is written after releasing `_lock`. A concurrent
`get_project()` could see `_model` as non-None then get None partway
through slot creation.

**File:** `service.py:187`
**Fix:** Move `self._model = None` inside the lock.

### PHASE2-003 | MEDIUM | Registry fixture directly sets _model

Test fixture bypasses `load_model()` via `reg._model = embedding_model`.
If `load_model()` ever gains side effects, tests silently skip them.
`test_load_model_idempotent` only tests the early-return path.

**File:** `test_service_registry.py:49`

### PHASE2-004 | INFO | watcher.py still supports legacy _graph_built_at poke

Fallback to `searcher._graph_built_at = 0.0` when `graph_cache is None`.
ADR says this should be replaced. Acceptable for backward compat.

**File:** `watcher.py:194`

### PHASE2-005 | LOW | close_project() doesn't release graph_cache or reranker GPU memory

Only `slot.store.close()` is called. CrossEncoder GPU memory and
GraphCache references are not explicitly released.

**File:** `service.py:176`

## Phase 3: FastMCP lifespan + health

### PHASE3-001 | MEDIUM | _ensure_watcher single-project limitation

Single module-level `_watcher_task` variable. Once started for one
project, subsequent calls with different roots silently do nothing.
Multi-project watching is impossible.

**File:** `mcp_server.py:168-188`
**Fix:** Track `dict[Path, asyncio.Task]` or document as alpha
limitation.

### PHASE3-005 | HIGH | health_handler "loading" status branch is dead code

During normal startup, `/health` is unreachable while lifespan runs
(Starlette only serves after lifespan yields). The "loading" branch
only triggers if `_model` is set to None after startup (e.g.,
`close_all` while running). Label is misleading.

**File:** `mcp_server.py:138-144`
**Fix:** Rename to "degraded" or "shutdown" for the post-startup
_model=None scenario.

### PHASE3-009 | MEDIUM | _gpu_sem created at module import time

`asyncio.Semaphore(1)` at import time. Safe on Python 3.13 (project
requirement) but worth documenting.

**File:** `mcp_server.py:39`

### PHASE3-010 | MEDIUM | Health test mutates _registry._model directly

Test reaches into `mod._registry._model = None` to test error state.
Couples test to internal ServiceRegistry structure.

**File:** `test_mcp_server.py:374-378`

### PHASE3-011 | LOW | No test for combined Starlette app composition

No test verifies `main()` constructs the Starlette app with both
`/mcp` and `/health` routes on the same app instance.

**File:** `test_mcp_server.py`

### PHASE3-006 | INFO | Stdio transport preserved correctly

`main()` falls through to `mcp.run(transport="stdio")` when
`port is None`. Claude Desktop compatibility confirmed.

### PHASE3-007 | INFO | stateless_http=True correctly set

Multi-agent sessions work without sticky sessions. Verified.

### PHASE3-008 | INFO | get_comp/RagComponents fully removed

Zero references in source tree. Clean removal confirmed.

## Phase 4: Service daemon commands

### PHASE4-001 | CRITICAL | _terminate_pid uses SIGTERM on Windows incorrectly

On Windows, `os.kill(pid, signal.SIGTERM)` calls `TerminateProcess`
(hard kill, no graceful drain — uvicorn's
`timeout_graceful_shutdown=30` never fires). With
`CREATE_NEW_PROCESS_GROUP`, `os.kill(pid, signal.SIGTERM)` may raise
`OSError` on some Python versions. `contextlib.suppress` swallows it,
leaving an orphaned service.

**File:** `cli.py:962-963`
**Fix:** On Windows, send `CTRL_BREAK_EVENT` to the process group
(`os.kill(pid, signal.CTRL_BREAK_EVENT)`) which uvicorn can catch.
Fallback to `TerminateProcess` via ctypes if that fails.

### PHASE4-002 | HIGH | PID file race between concurrent service start calls

Between `_read_service_status()` returning None and
`_write_service_status()`, a second `service start` can pass the same
check. Both spawn; one overwrites the other's status file. Loser's
process runs orphaned.

**File:** `cli.py:992-1015`
**Fix:** Use file lock on `service.json` before the
read-check-spawn-write sequence.

### PHASE4-003 | HIGH | _write_service_status is not atomic

`Path.write_text()` truncates then writes. Crash mid-write leaves
corrupt status file. Project uses atomic writes (tmp + os.replace)
elsewhere.

**File:** `cli.py:849`
**Fix:** Write to `.tmp` then `os.replace()`.

### PHASE4-004 | MEDIUM | _spawn_service leaks log file handle

`log_fh = open(...)` is never closed by the parent process after
Popen. The Popen object is immediately discarded, so proc.returncode
is never reaped on Unix (potential zombie).

**File:** `cli.py:933, 950`
**Fix:** Close `log_fh` after Popen returns. Store proc reference.

### PHASE4-005 | MEDIUM | _is_pid_alive false positive on Windows

`OpenProcess` returns a handle for terminated-but-not-closed processes.
Causes `service start` to falsely detect a running service.

**File:** `cli.py:885-893`
**Fix:** After `OpenProcess`, call `GetExitCodeProcess`; if not
`STILL_ACTIVE (259)`, process is dead.

### PHASE4-006 | MEDIUM | Port conflict detection is indirect

Another app on port 8766 causes child crash detected only via PID
liveness in poll loop. No programmatic port check.

**File:** `cli.py:1026-1037`
**Fix:** Pre-probe port with TCP connect/bind check before spawning.

### PHASE4-008 | LOW | Tests use monkeypatch (violates testing mandates)

`TestServiceDaemonHelpers` uses `monkeypatch.setattr` to redirect
`_status_file`. Project mandates forbid monkeypatches.

**File:** `test_cli.py:219, 234, 253, 267, 281`

## Phase 5: Model prefetch

### PHASE4-007 | MEDIUM | Warmup: no auth guidance for gated SPLADE model

`snapshot_download` without token fails with 401 for `naver/splade-v3`.
Generic `except Exception` shows "failed" with no guidance about
`HF_TOKEN` or `huggingface-cli login`.

**File:** `cli.py:1221-1225`
**Fix:** Detect 401/403, print auth guidance.

### PHASE4-009 | INFO | HF_HUB_DOWNLOAD_TIMEOUT=60 may be short

For first download of Qwen3 (~1.2GB) on slow connections. `setdefault`
is correct (doesn't override user env). Consider 300s.

**File:** `cli.py:1197`

---

## Round 2: Thread safety deep dive

### THREAD-001 | MEDIUM | `_get_reranker()` lacks synchronization

`VaultSearcher._get_reranker()` at `search.py:250-282` uses a bare
`if self._reranker is not None: return` check with no lock. Two
concurrent `search_vault` calls dispatched via `anyio.to_thread` can
both instantiate `CrossEncoder` on GPU (~560MB VRAM each). Same
pattern as PHASE2-001 but on a different object.

### THREAD-002 | MEDIUM | `_ensure_watcher` TOCTOU race on `_watcher_task`

`mcp_server.py:168-188`: checks `_watcher_task is None` then assigns
later. Two tool handlers finishing near-simultaneously could both
enter and spawn duplicate watchers. Narrow window since no `await`
between check and assignment, but design relies on this implicitly.

### THREAD-003 | HIGH | `_gpu_sem` bypassed by `get_index_status` and other tools

`get_index_status` (`mcp_server.py:558-602`) calls
`_registry.get_project(root)` which may trigger `_create_slot()` →
model loading **without** acquiring `_gpu_sem`. Similarly
`get_vault_document` and `get_code_file` bypass the semaphore. First
call for a new project root triggers full store creation concurrently
with a search tool holding `_gpu_sem`.

### THREAD-004 | LOW | `reset_engine()` in api.py writes `_engine = None` outside lock

Could race with `get_engine()`. The store `close()` + reassignment
is not atomic. Test-only function but still a correctness gap.

### THREAD-005 | MEDIUM | Qdrant local SQLite concurrent write contention

`QdrantClient(path=...)` is backed by SQLite with 5-second busy
timeout. Concurrent `reindex_vault` + `reindex_codebase` upserts
to different collections contend on the SQLite WAL lock. Can produce
`database is locked` errors under heavy concurrent indexing.

### THREAD-006 | LOW | `health()` iterates `_projects` dict without lock

`ServiceRegistry.health()` at `service.py:191-202` reads
`self._projects` without `_lock`. A concurrent mutation could cause
`RuntimeError: dictionary changed size during iteration`.

## Round 2: Error handling + edge cases

### ERROR-001 | MEDIUM | `load_model()` failure produces raw traceback

If `EmbeddingModel()` raises during lifespan startup, the exception
propagates as an unhandled traceback with no user-friendly guidance.
Contrast with `cli.py`'s `_handle_gpu_error`.

**File:** `service.py:79`, `mcp_server.py:98`

### ERROR-002 | HIGH | `_create_slot()` partial failure leaks VaultStore

`VaultStore(root)` opens Qdrant at `service.py:146`. If any subsequent
constructor raises, the exception propagates without closing the
already-opened store. The slot is never inserted into `_projects`,
so `close_all()` never closes it. Qdrant lock file remains held.

**File:** `service.py:125-164`
**Fix:** try/except around `_create_slot` body; call `store.close()`
on failure.

### ERROR-003 | MEDIUM | `_health_probe` treats HTTP 500 same as "not started"

`urllib.request.urlopen` raises `HTTPError` for 5xx. Caught by bare
`except Exception`, returns `None`. A persistently unhealthy service
spins the full 30s deadline with misleading "not ready" message.

**File:** `cli.py:914-919`

### ERROR-004 | LOW | `service.json` missing "port" falls back to caller default

`status.get("port", port)` at `cli.py:996` falls back silently.
If the existing service runs on a different port, health probe hits
the wrong port. Validator checks "pid" but not "port".

### ERROR-005 | MEDIUM | Explicit CUDA check in lifespan serves no purpose

`mcp_server.py:89-90`: when `cuda_ok is False`, logs error but does
not raise. Proceeds to `load_model()` which will raise anyway via
`_check_rag_deps()`. Early check only adds a log line before the
inevitable crash.

### ERROR-006 | LOW | `snapshot_download` interrupt leaves partial HF cache

Ctrl+C during warmup leaves `.incomplete` marker files. Self-healing
on next run but user gets no indication.

### ERROR-007 | HIGH | Bind failure in `uvicorn.run()` leaks VRAM

If `uvicorn.run()` at `mcp_server.py:828` raises (bind failure),
`_registry.close_all()` is NOT called because cleanup only happens
in the `finally` block of `service_lifespan`, which only runs if
the lifespan successfully yielded. Models loaded into VRAM are never
freed until process exit.

**File:** `mcp_server.py:802-834`

### ERROR-008 | LOW | No .vault/ directory produces silent empty results

When `_create_slot` builds components for a root with no `.vault/`,
no error is raised. Searches return empty results. Confirmed-by-design
(pre-service-graph behavior was identical).

## Round 2: Test coverage gaps

### TESTGAP-001 | HIGH | `_terminate_pid()` has zero test coverage

`cli.py:953` is never called in any test. No verification of SIGTERM,
Windows behavior, or error suppression.

### TESTGAP-002 | HIGH | `_spawn_service()` has zero test coverage

`cli.py:922` is never exercised. No verification of subprocess
creation, log file passing, platform flags, or spawn failure.

### TESTGAP-003 | HIGH | `service_start()` command has zero test coverage

The entire start flow (existing-service detection, spawn, health
poll loop, timeout, stale-PID cleanup) is untested.

### TESTGAP-004 | MEDIUM | `service_stop()` only tests "not running" path

Happy path (alive PID, termination, status removal) and stale PID
path are untested.

### TESTGAP-005 | MEDIUM | `service_status()` only tests "not running" path

Running+healthy path (`cli.py:1117`) is untested.

### TESTGAP-006 | MEDIUM | `GraphCache.get()` after construction failure untested

Retry-suppression behavior (None returned for full TTL after failure)
is not verified.

### TESTGAP-007 | MEDIUM | `GraphCache.invalidate()` concurrent with `get()` untested

Lock should serialize but interaction is unverified.

### TESTGAP-008 | MEDIUM | `ServiceRegistry.health()` after `close_all()` untested

Combined with PHASE2-002 (model set to None outside lock), this
could expose a race.

### TESTGAP-009 | MEDIUM | MCP tools with `project_root` parameter untested end-to-end

All tests are structural. No test invokes a tool handler with
`project_root` set, let alone two different roots in one session.

### TESTGAP-010 | LOW | `_ensure_watcher` second-project no-op untested

Single-project limitation (PHASE3-001) has no test verification.

### TESTGAP-011 | LOW | `_health_probe()` timeout/exception paths untested

Only connection-refused path is tested.

### TESTGAP-012 | INFO | `monkeypatch` also used in `test_mcp_server.py`

5 tests in `TestResolveRoot` and `TestHealthHandler` use
`monkeypatch`. R1 audit only flagged `test_cli.py`.

## Round 2: ADR compliance verification

### ADR-D1 | COMPLIANT | Global resident service with dmypy pattern

All specified elements confirmed: global status file, port 8766
default, `VAULTSPEC_RAG_PORT` env var, `CREATE_NO_WINDOW`,
exponential backoff health polling.

### ADR-D2 | COMPLIANT | Raw HTTP GET /health endpoint

Starlette `Route("/health", health_handler)` returns correct JSON
schema. Not an MCP tool.

### ADR-D3 | COMPLIANT | Unified graph cache with DI

Public `GraphCache` with lock+TTL, `graph_provider` in
`VaultSearcher`, `_graph_built_at` poke fully removed from
`mcp_server.py`. Per-project instances in `ProjectSlot`.

### ADR-D4 | COMPLIANT | Model prefetch via `service warmup`

`snapshot_download` for all 3 models, CUDA check first,
`HF_HUB_DOWNLOAD_TIMEOUT=60`.

### ADR-D5 | COMPLIANT | FastMCP lifespan + Starlette mounting

Eager model loading, `Mount("/mcp") + Route("/health")`,
`timeout_graceful_shutdown=30`, stdio preserved, `stateless_http=True`.

### ADR-D6 | COMPLIANT | ServiceRegistry in service.py

Shared model + per-project dict, MCP tools accept `project_root`,
`api.py` facade preserved.

**All six ADR decisions are COMPLIANT. No divergences.**

## Updated summary

| Severity | R1 | R2 | Total | Key issues |
|----------|----|----|-------|-----------|
| CRITICAL | 1 | 0 | 1 | Windows SIGTERM |
| HIGH | 4 | 5 | 9 | GPU sem bypass, VaultStore leak, VRAM leak on bind, test gaps (terminate/spawn/start) |
| MEDIUM | 9 | 11 | 20 | Thread safety (reranker, watcher, SQLite), error handling, test coverage |
| LOW | 4 | 5 | 9 | Various edge cases, partial cleanup |
| INFO | 6 | 1 | 7 | Documentation, monkeypatch scope |

**ADR compliance: 6/6 COMPLIANT.**

**Priority fixes before merge:**

- PHASE4-001 (CRITICAL): Windows _terminate_pid
- THREAD-003 (HIGH): _gpu_sem bypass
- ERROR-002 (HIGH): VaultStore leak on partial slot creation
- ERROR-007 (HIGH): VRAM leak on bind failure
- PHASE2-001 (HIGH): load_model thread safety
- TESTGAP-001/002/003 (HIGH): Zero coverage on service lifecycle
