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

## Summary

| Severity | Count | Key issues |
|----------|-------|-----------|
| CRITICAL | 1 | Windows SIGTERM behavior in _terminate_pid |
| HIGH | 4 | load_model thread safety, PID race, non-atomic write, dead "loading" status |
| MEDIUM | 9 | Various (close_all lock, watcher single-project, handle leak, PID false positive, port detection, warmup auth, test coupling) |
| LOW | 4 | Tautological test, failure retry suppression, GPU memory, monkeypatch use |
| INFO | 6 | Dead code, verified correctness, documentation |

**Immediate action needed:** PHASE4-001 (CRITICAL) and the 4 HIGH
findings should be addressed before merging the PR.
