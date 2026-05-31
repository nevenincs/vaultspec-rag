---
tags:
  - '#adr'
  - '#store-eviction-log-rotation'
date: 2026-04-12
related:
  - '[[2026-04-12-store-eviction-log-rotation-research]]'
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-adr]]'
---

# `store-eviction-log-rotation` adr: `bounded-multi-tenant-service` | (**status:** `accepted`)

Review trail: Reviewed by: 2 parallel reviewers (concurrency/lifecycle, Windows-IO/CLI), 2026-04-12; all critical and major findings addressed.

Reviewed by: 2 parallel reviewers (concurrency, Windows-IO)

## Problem Statement

The `vaultspec-rag` HTTP/MCP service is designed as a long-lived,
multi-tenant daemon. Two resources currently grow without bound and
were explicitly deferred to beta by the service-graph ADR:

1. **`ServiceRegistry._projects`** — every distinct workspace root
   visited by a search or index call allocates a `ProjectSlot`
   containing a `VaultStore` (Qdrant local client with file locks),
   a `VaultSearcher`, two indexers, a `GraphCache`, and a filesystem
   watcher task. Nothing prunes the dict today except the
   explicit-but-unreachable `close_project(root)` path and the
   lifespan `close_all()`. Over weeks of agent traffic the daemon
   accumulates file handles, Qdrant segments, and in-memory graph
   caches until the operator manually restarts. VRAM is NOT the
   leak (models are shared on the registry); disk, file descriptors
   and graph memory are.

1. **`service.log`** — the parent CLI's `_spawn_service` opens the
   log file in append mode, dups it onto the child's stdout/stderr,
   and closes its own copy. The child installs no `logging.Handler`
   pointed at the file; its own stderr `RichHandler` (installed by
   `vaultspec_core.logging_config`) happens to write to the redirected
   FD. Result: the file collects three intermingled streams
   (child stdout, uvicorn/starlette logs, RichHandler output) with
   no rotation. A DEBUG-level reindex fills disk.

Issue #45 is the explicit beta gate that must resolve both.

## Considerations

The research phase examined rotation placement (child-side vs parent
pipe vs external tool), synchronization primitives (refcount vs
RWLock vs skip-busy), eviction timing (lazy vs background thread),
transport (MCP tool vs Starlette admin route vs IPC file), and
config defaults (opt-in vs conservative-on). The options analysis
is persisted in the linked research document; this ADR records
the decisions and their rationale. Hard constraints we inherit:

- `ServiceRegistry._lock` is the only coarse global lock, and the
  existing three-level lock dance (global, per-root, global again)
  in `get_project` must be preserved so parallel cold-starts of
  *different* roots still proceed concurrently.
- `close_project(root)` already sequences watcher teardown before
  store close via `_on_close_project` — eviction must reuse this
  exact callback path or risk race between watcher and closed
  Qdrant client.
- The test mandate forbids mocks, patches, stubs, skips and fakes.
  All verification runs against real subprocess, real GPU, real
  Qdrant.
- Rotation must work on Windows, which is the primary development
  platform. The Windows FD-dup gotcha described in the research is
  the single largest risk in the rotation design.
- The service-graph ADR's `_on_close_project` callback assumes
  that the watcher task tolerates cancellation mid-`incremental_index`
  — confirmed safe by Task #43's atomic metadata writes
  (`write-to-.tmp + os.replace`).

## Constraints

- **No background sweeper thread.** The alpha service already has
  enough thread/lifespan complexity (watcher tasks, FastMCP session
  manager, uvicorn workers). Eviction must be lazy — triggered by
  traffic, never by a wall-clock timer.
- **No mid-use close.** An in-flight search against a slot must
  never see its `VaultStore.close()` called from underneath it.
  The discipline is refcount + skip-busy; the evictor only touches
  `ref_count == 0` slots.
- **No new transport.** CLI and MCP must share one wire. The existing
  FastMCP streamable-http server at `/mcp` is the transport for both
  new admin tools; `/health` is the only non-MCP endpoint that
  remains, for the same reason it exists today (MCP has no ping).
- **No core changes for rotation.** `vaultspec-core`'s
  `logging_config` installs a stderr `RichHandler` for short-lived
  CLI/MCP processes and has no daemon semantics. Adding a file
  handler with rotation knobs would force every core consumer to
  pay the cost. Rotation belongs in `rag`.
- **Backwards compatibility for existing configs.** Users running
  the alpha service today have config files with none of the new
  keys. The defaults must kick in silently and cause no surprise
  beyond the one documented behavioral change (eviction at 30 min).

## Implementation

The ADR records ten discrete decisions. Each decision below pairs
with the ground-truth file it touches (named in inline code) and a
rationale paragraph anchored in the research.

### D1 — Child-side `DaemonRotatingFileHandler` with re-`dup2`

A new module `src/vaultspec_rag/service_logging.py` defines
`DaemonRotatingFileHandler`, a subclass of
`logging.handlers.RotatingFileHandler` that overrides `doRollover`:

```python
class DaemonRotatingFileHandler(RotatingFileHandler):
    def doRollover(self) -> None:
        # logging.Handler.acquire() is reentrant (RLock); emit() already
        # holds it when it dispatches us, so this self.acquire() is a
        # no-op in the common path but defensive when called directly
        # (e.g. from a SIGHUP handler in future work).
        self.acquire()
        try:
            super().doRollover()
            if self.stream is not None:
                fd = self.stream.fileno()
                os.dup2(fd, 1)
                os.dup2(fd, 2)
        except Exception:
            # Best-effort: if rollover failed mid-flight, leave fds 1/2
            # untouched. The next emit() will retry rollover via shouldRollover.
            logger.exception("DaemonRotatingFileHandler.doRollover failed")
            raise
        finally:
            self.release()
```

**doRollover failure mode.** If `super().doRollover()` raises (e.g.
transient Windows file-lock conflict), fds 1/2 keep their existing
kernel reference to the original file, which may have been renamed
to `service.log.1` or may still be `service.log` depending on how
far rollover got. Subsequent log records will retry rollover on the
next size check. This is acceptable degradation: at worst, one
rotation cycle's worth of stdout output lands in `service.log.1`
instead of `service.log`. Hard failure (EBADF) is not possible
because `dup2` is only attempted on a non-None stream.

**RLock reentrancy.** `logging.Handler.acquire()` returns a
`threading.RLock` (created by `Handler.createLock` in CPython's
`Lib/logging/__init__.py`), so the explicit `self.acquire()` inside
`doRollover` is safe to call recursively from `emit()`, which
already holds the same lock when it dispatches the record.

#### Install ordering (CRITICAL)

`vaultspec_core.logging_config.configure_logging()` clears all root
handlers (`for handler in root.handlers[:]: root.removeHandler(handler)`).
`DaemonRotatingFileHandler` MUST therefore be installed in
`mcp_server.main()` **AFTER** the call to `configure_logging()` and
**BEFORE** `uvicorn.run()`. Order:

```python
def main() -> None:
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    configure_logging()                              # core wipes handlers
    install_daemon_log_rotation()                    # adds rotating handler + dup2 fds 1/2
    uvicorn.run(mcp_app, host=..., port=args.port)   # may add its own access loggers AFTER ours
```

`install_daemon_log_rotation()` is a new module-level helper in
`logging_config.py` that constructs the handler, attaches it to the
root logger, and performs the initial `os.dup2()` of fds 1 and 2
onto the handler's stream. It is idempotent (no-op if a
`DaemonRotatingFileHandler` is already on the root logger).

The handler is installed in `mcp_server.main()` **before** uvicorn
boot and **before** any module-level logger fires. Installation
attaches the handler to the root logger AND re-`dup2`s FDs 1 and 2
onto the freshly-opened stream, so `print()`, uvicorn access logs,
and any bare C-level writes land in the rotated file alongside the
formatted log records. The parent-side `_spawn_service` is
unchanged — it still opens the log in append mode and passes the
FD as `stdout` / `stderr`. That FD survives for the few lines of
Python the child runs before `main()` installs the handler and
replaces it via `dup2`.

**Rationale.** The research established that parent-side rotation
(A2) is non-viable because the parent CLI exits immediately after
`_spawn_service` — a rotator thread would die with it. External
rotation (A3) is a cross-platform nightmare. That leaves
child-side rotation, and the Windows-specific trap identified in
the research is the reason subclassing is required: after the first
rollover, `RotatingFileHandler` closes and reopens `self.stream`,
but the dup'd FDs 1 and 2 still reference the *original* kernel
inode, which `os.rename` has just moved to `service.log.1`. Without
a re-`dup2`, stdout/stderr get stuck writing to the rotated file
forever and the backup-count accounting silently goes wrong. The
acquire/release around `super().doRollover()` is the root logger's
own `RLock` — it is already held by every `emit()` call, so the
re-dup block is serialized with formatted writes. Any concurrent
emit() blocks on the same lock; there is no thread race on the
Python side. Windows UCRT's `_dup2` holds the per-fd CRT lock for
the duration of the close+duplicate sequence, so concurrent fd-1/2
writes from other threads either complete on the original inode
before `dup2` returns or block until it returns. No partial writes
are exposed.

**Known limitation.** A third-party raw stdout write (e.g. uvicorn
access log if configured to print directly, or a native C extension)
that happens in the microsecond window between `super().doRollover()`
and the second `dup2` will land in `service.log.1` instead of the
new `service.log`. The research explicitly accepted this as benign:
the window is bounded to rollover events (a few per day at
10 MiB × 5), and any Python-logging-formatted write is protected
because the handler's `RLock` is held throughout `doRollover`.
This edge is documented in Consequences below.

### D2 — Rotation lives in rag, not core

`vaultspec-core`'s `logging_config.py` is a thin wrapper that
installs a stderr `RichHandler` for short-lived CLI and MCP stdio
processes. It has no concept of a persistent daemon log file, no
rotation knobs, and no consumers that would benefit from either.
Pushing the rotating file handler into core would force every core
CLI command and every core-driven MCP server to carry the cost.
The service daemon is a rag-only concern, so rotation stays in rag.

**Rationale.** The research section "Core vs rag placement" is
explicit on this point and recommends deferring any core-level
rotation to a future enhancement that is optional and disabled by
default. Blocking #45 on a core release would gate beta on an
orthogonal change; we do not. The follow-up note is captured in
"Open questions resolved" and "Out of scope" below.

### D3 — `ServiceRegistry` lease API with `last_access` and `ref_count`

`ProjectSlot` in `src/vaultspec_rag/service.py` gains two mutable
fields (the dataclass is already non-frozen):

- `last_access: float` — monotonic seconds, set to
  `time.monotonic()` on every successful lease acquire.
- `ref_count: int` — incremented on lease acquire, decremented on
  lease release. Never mutated or read outside `_lock`.

The registry grows a context-manager lease API as the sole
chokepoint for request-path access:

```
@contextlib.contextmanager
def lease(self, root: Path) -> Iterator[ProjectSlot]:
    slot = self._acquire(root)     # _get_or_create + ++ref_count under _lock
    try:
        yield slot
    finally:
        self._release(slot)        # --ref_count under _lock
```

The existing non-leasing accessor is renamed `peek_project(root) -> ProjectSlot`
and is reserved for non-request setup (lifespan wiring, watcher
installation). `peek_project` takes the lock, optionally creates
the slot, and returns it **without** bumping `ref_count` or
touching `last_access`. `_ensure_watcher` in `src/vaultspec_rag/mcp_server.py`
(around lines 193–235) MUST be converted from `get_project` to
`peek_project`, because the watcher is not a request — it lives
inside the slot's lifetime and wiring it should not keep the slot
"busy" forever. The watcher itself, when it later fires
`incremental_index` callbacks, uses its own short-lived `lease`
context so those writes correctly participate in refcount tracking.

**Rationale.** The research confirmed by grep that every request
path already funnels through `get_project(root)`. Storing
`last_access` and `ref_count` on the slot wins on locality vs a
sibling `dict[Path, float]`. A context-manager lease is strictly
safer than paired `acquire/release` calls scattered through
`mcp_server.py` — a single missed `release` would pin the slot
as permanently busy and silently disable eviction. The research
flagged `_ensure_watcher` specifically as the call site that
*must not* bump refcount (unexpected-findings bullet 2), which is
the cleanest proof that the lease API must be an explicit opt-in
and that `get_project` cannot be repurposed to always bump.

#### Migration sites

Every callsite that must change from `get_project` to either
`lease` or `peek_project`:

- `src/vaultspec_rag/api.py` — every facade function that accesses
  a slot → use `lease()` (will be rewritten as part of D5).
- `src/vaultspec_rag/mcp_server.py:_ensure_watcher` (~line 212) →
  `peek_project` (watcher wiring is non-request-path).
- `src/vaultspec_rag/mcp_server.py:service_lifespan` — any preload
  or eager-init paths → `peek_project`.
- `src/vaultspec_rag/mcp_server.py` MCP tool handlers
  (`search_vault`, `search_codebase`, `reindex_vault`,
  `reindex_codebase`, `get_index_status`, `get_code_file`) →
  `lease()`.
- Any test that touches `_registry.get_project(...)` → split per
  intent: lease for request-shaped tests, peek for wiring tests.

Teardown ordering invariant: `_close_evicted` (and `close_project`)
MUST call `_on_close_project(root)` BEFORE removing the slot from
`_projects`, preserving the existing watcher-stops-before-store-closes
ordering at `service.py:286-294`.

### D4 — Skip-busy lazy sweep + LRU admission

Eviction is entirely lazy, triggered only by traffic.

**Acquire path.** `lease()` delegates to `_acquire()`:

```python
def _acquire(self, root: Path) -> ProjectSlot:
    root = root.resolve()
    with self._lock:
        if self._shutting_down:
            raise RuntimeError("ServiceRegistry is shutting down")
        slot = self._projects.get(root)
        if slot is None:
            slot = self._admit_with_lru(root)   # may evict, may raise RegistryFullError
        slot.last_access = time.monotonic()
        slot.ref_count += 1
        self._sweep_idle()                       # opportunistic
        return slot
```

The `_shutting_down` check is performed BEFORE any admission or
refcount mutation. This guarantees `close_all()`'s drain loop sees
a monotonically non-increasing `ref_count` and terminates within
the deadline regardless of incoming traffic.

**Idle sweep.** Called from `_acquire()` while `_lock` is held:

```python
def _sweep_idle(self) -> None:
    """Caller MUST hold self._lock. Returns with self._lock still held."""
    if self._idle_ttl_seconds <= 0:
        return
    now = time.monotonic()
    victims = [
        root for root, slot in self._projects.items()
        if slot.ref_count == 0 and (now - slot.last_access) >= self._idle_ttl_seconds
    ]
    if not victims:
        return
    # Drop _lock for the actual teardown to avoid recursive acquire on
    # close_project's own _lock. Re-checking ref_count after re-acquire
    # is unnecessary because _shutting_down is False here and a slot can
    # only acquire a fresh ref via lease(), which itself takes _lock.
    self._lock.release()
    try:
        for root in victims:
            self._close_evicted(root, reason="idle")
    finally:
        self._lock.acquire()
```

Sibling helper used by both the sweeper and the LRU admission path:

```python
def _close_evicted(self, root: Path, reason: str) -> None:
    """Tear down a slot that the sweeper or LRU admit selected.

    Equivalent to close_project() but logs eviction reason and is the
    only path that should be called from inside the registry's own
    sweep/LRU codepaths.
    """
    self.close_project(root)
    logger.info("Evicted ProjectSlot %s (reason=%s)", root, reason)
```

`_sweep_idle` is called by `lease()` while `_lock` is held; it
temporarily releases `_lock` to invoke `close_project` (which
itself reacquires `_lock` via its existing path), then reacquires
`_lock` before returning. This avoids the deadlock that would
otherwise occur because `service.py`'s `_lock` is `threading.Lock`,
not `RLock`. Switching `_lock` to `RLock` is rejected because the
additional reentrancy makes the lock-ordering invariant harder to
audit.

`idle_ttl == 0` disables time-based eviction entirely.

**LRU admission.** On every `_create_slot()` admission path, if
`len(self._projects) >= self._max_projects` and `self._max_projects > 0`,
select the slot with the smallest `last_access` where
`ref_count == 0`, evict it, and then admit the new slot. If NO
slot is evictable (all busy), raise a new `RegistryFullError`.
The MCP tool layer translates this to a structured JSON error
so the user sees a clear "registry full, all slots busy" message.

```
def _admit_with_lru(self, root: Path) -> None:
    if self._max_projects <= 0:
        return
    if len(self._projects) < self._max_projects:
        return
    candidates = [
        (slot.last_access, root2)
        for root2, slot in self._projects.items()
        if slot.ref_count == 0
    ]
    if not candidates:
        raise RegistryFullError(self._max_projects)
    candidates.sort()
    victim = candidates[0][1]
    self._close_evicted(victim, reason="lru")
```

#### Error propagation

`RegistryFullError` is a new exception in `service.py`. The MCP
tool handlers in `mcp_server.py` MUST catch it explicitly and
return a structured dict rather than letting FastMCP serialize it
as a generic JSON-RPC error:

```python
try:
    with _registry.lease(project_root) as slot:
        ...
except RegistryFullError as e:
    return {
        "ok": False,
        "error": "registry_full",
        "message": str(e),
        "max_projects": _registry.max_projects,
        "busy_projects": [str(p) for p in _registry.busy_roots()],
    }
```

The same shape is added to `list_projects` and `evict_project` so
all admin tooling speaks one error vocabulary. CLI consumers
(`_try_mcp_admin`) check `result.get("ok") is False` and render
the structured error.

**Rationale.** The research's option-(iii) hybrid is adopted: lazy
sweep covers the "traffic resumes against a stale project" case;
LRU admission gives a hard upper bound on slot count. A background
sweeper thread (option ii) is rejected for the reasons listed in
Constraints — shutdown coordination, lock discipline, and "no
benefit at a bounded 16-slot scale." Skip-busy is the right
synchronization primitive because it is non-blocking: an evictor
that encounters `ref_count > 0` simply moves on. The research's
R36-C1 precedent (concurrent graph rebuilds under one lock) is
the template — eviction decisions happen atomically inside `_lock`,
the actual teardown runs outside it, and any concurrent request
for the victim root simply creates a fresh slot with no
cross-contamination of the old one.

### D5 — Collapse `api.py._engine` into `ServiceRegistry`

Direct source inspection of `src/vaultspec_rag/api.py` confirms
that `_engine` is **still a parallel cache** as of 2026-04-12.
It is a single-slot `_Engine` singleton holding its own `VaultStore`,
`VaultSearcher`, `VaultIndexer`, `CodebaseIndexer`, and `GraphCache`
for one `root_dir` at a time. `get_engine(root_dir)` swaps the
singleton when called with a different root, closing the previous
store. This pre-dates `ServiceRegistry` and was never migrated.
It is wholly independent of `_registry._projects` and does not
participate in refcount, idle TTL, LRU cap, or the shared
reranker. Two parallel caches against the same Qdrant files is a
correctness liability: a search issued via `search_vault()`
(the `api.py` path) and a search issued via the MCP tool
`search_vault()` (the registry path) against the same root would
each hold their own `VaultStore` with overlapping file locks, and
eviction on one side would leave the other unaware.

This ADR mandates the `_engine` cache be removed as part of
execution Phase 1. Every public facade function in `api.py`
(`index`, `index_codebase`, `search_vault`, `search_codebase`,
`list_documents`, `get_related`) is rewritten to call
`ServiceRegistry.lease(root)` and delegate to the slot's
components. The module-level `_engine` global, `_engine_lock`,
the `_Engine` class, and `reset_engine()` are deleted.
`reset_engine`'s only caller — test fixtures — is migrated to
`ServiceRegistry.close_all()`.

**Rationale.** The service-graph ADR's stated goal was a single
per-project component owner, and that goal is unfulfilled as long
as `api.py` keeps its own parallel cache. Eviction cannot work
correctly across two independent caches. The collapse is small
(the `api.py` facade functions are one-liners already) and
strictly reduces cache complexity.

**GraphCache relocation.** `GraphCache` currently lives in
`api.py`. This ADR mandates moving it to a new module
`src/vaultspec_rag/graph_cache.py`. `service.py` and any test
importing `from vaultspec_rag.api import GraphCache` must be
updated to import from the new module. `api.py` is shrunk to a
thin re-export shim (or removed entirely if no consumers remain —
that decision is left to the plan phase).

### D6 — `close_all()` graceful drain

`close_all()` today pops every slot and calls `store.close()`
under `_lock`. With refcount in play, this would forcibly close
stores that an in-flight request still holds. The new shutdown
sequence is a bounded drain:

```
def close_all(self) -> None:
    with self._lock:
        self._shutting_down = True
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with self._lock:
            busy = [r for r, s in self._projects.items() if s.ref_count > 0]
        if not busy:
            break
        time.sleep(0.1)
    with self._lock:
        for root, slot in list(self._projects.items()):
            if slot.ref_count > 0:
                logger.warning(
                    "Force-closing busy slot %s (ref_count=%d)",
                    root, slot.ref_count,
                )
            # existing close logic: _on_close_project, store.close, etc.
```

The 5-second drain deadline is conservative and was chosen to be
longer than any realistic single search latency (query embedding

- hybrid + rerank ≈ 100ms typical, 1s worst case) but short
  enough that `uvicorn` lifespan shutdown never looks hung. The
  constant is intentionally **not** made configurable in this ADR.

**Rationale.** The research's unexpected-findings bullet 3 called
out the shutdown-semantics question explicitly. A bounded drain
is the minimum correctness fix: it gives in-flight requests a
best-effort chance to complete before forcible close, logs a
warning when the deadline expires with busy slots still present
(so operators can spot pathological long-tail requests), and
preserves the existing `_on_close_project` teardown order.

### D7 — Two new MCP tools and `service projects` CLI subcommand

**MCP tools** (on the existing FastMCP `mcp_app`):

- `list_projects() -> dict` returns:

  ```
  {
    "projects": [
      {
        "root": "C:/code/foo",
        "last_access_iso": "2026-04-12T10:14:33Z",
        "idle_seconds": 42.1,
        "ref_count": 0
      },
      ...
    ],
    "max_projects": 16,
    "idle_ttl_seconds": 1800
  }
  ```

- `evict_project(root: str) -> dict` returns one of:

  ```
  { "evicted": true,  "reason": "forced" }    // manual evict succeeded
  { "evicted": false, "reason": "busy" }       // ref_count > 0
  { "evicted": false, "reason": "not_found" }  // unknown root
  ```

  The manual `evict_project` MCP tool's success path uses
  `reason="forced"`. `"idle"` is reserved for internal sweeper
  logging only and never appears in the MCP response. Manual
  eviction with `ref_count > 0` returns `reason="busy"` and does
  not block — the operator is expected to retry.

Both tools resolve `root` via `Path(root).resolve()` before lookup,
matching the `get_project` discipline.

**CLI side** (in `src/vaultspec_rag/cli.py`):

- A new `service_projects_app = typer.Typer()` is registered on
  the existing `service_app` via
  `service_app.add_typer(service_projects_app, name="projects")`.
- Two commands: `service projects list [--port N]` and
  `service projects evict <root> [--port N]`.
- Both commands call a new helper `_try_mcp_admin(tool_name, args, port)`.
  `_try_mcp_admin` is a brand-new helper in `cli.py`, NOT a
  generalization of `_try_mcp_search`. Signature:
  `_try_mcp_admin(tool_name: str, args: dict, port: int | None) -> dict | None`.
  Behavior: (a) connects to the running service via
  `streamable_http_client`, (b) calls the named tool with the
  given args, (c) parses the response as a dict, (d) returns the
  dict on success or `None` ONLY when the service is unreachable
  (connection refused). All other failures (malformed response,
  tool error, busy slot) return the error dict so the CLI can
  render a meaningful message. The CLI distinguishes "service
  down" (`_try_mcp_admin` returns `None` → render "Service is not
  running, start it with `vaultspec-rag service start`") from
  "tool error" (`_try_mcp_admin` returns `{"ok": False, ...}` →
  render the structured error). The helper uses the same
  `streamable_http_client` + `ClientSession` pattern proven in
  Task #19 (PR #38).

**Rich table for `service projects list`.** Columns: `Root`
(truncated to 60 chars from the right with `…`), `Idle`
(humanized: `2m 14s`, `1h 5m`), `Refs`, `Last access` (HH:MM:SS
local time). Sort by `last_access` descending (most-recently-
accessed first). Footer line: `{n}/{max} slots, idle TTL {ttl}s`.

**Exit codes for `service projects evict`:**

- `0` — slot evicted (`reason in {"idle","forced"}`)
- `1` — slot was busy (`reason="busy"`), CLI prints "slot busy, retry shortly"
- `2` — slot not found (`reason="not_found"`)
- `3` — service is not running (`_try_mcp_admin` returned `None`)

**Rationale.** The research's option-(D1) analysis showed that a
Starlette `/admin/projects` route would be a second transport,
a second auth boundary, and a second client to maintain in
`cli.py`. Every existing admin-ish operation (`get_index_status`,
`reindex_vault`, `reindex_codebase`, `get_code_file`) is already a
FastMCP tool, and Task #19 proved the CLI-as-MCP-client fast path
works against tools. Consistency and minimal surface area.

### D8 — Config keys

Four new keys on `VaultSpecConfigWrapper.DEFAULTS` in
`src/vaultspec_rag/config.py`:

| Key                        | Default    | Env var                                  |
| -------------------------- | ---------- | ---------------------------------------- |
| `service_idle_ttl_seconds` | `1800`     | `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` |
| `service_max_projects`     | `16`       | `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`     |
| `service_log_max_bytes`    | `10485760` | `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`    |
| `service_log_backup_count` | `5`        | `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` |

Matching `EnvVar` enum entries: `SERVICE_IDLE_TTL_SECONDS`,
`SERVICE_MAX_PROJECTS`, `SERVICE_LOG_MAX_BYTES`,
`SERVICE_LOG_BACKUP_COUNT`, with the `VAULTSPEC_RAG_` prefix
applied by the existing env-override machinery.

Each knob is disabled by setting its value to `0`:

- `service_idle_ttl_seconds=0` disables idle sweeping.
- `service_max_projects=0` disables the LRU cap.
- `service_log_max_bytes=0` disables rotation (handler still
  installs, but never rolls — equivalent to a plain `FileHandler`).
- `service_log_backup_count=0` rolls-and-truncates without keeping
  backups (standard `RotatingFileHandler` semantics).

**Defaults are ON**, not opt-in. The research's "opt-in vs
conservative-on" section argued this explicitly: #45 IS the beta
gate, there is no large installed base to surprise, the leak is
real and silent, and 30 minutes is long enough that no active
workflow is evicted mid-session. 50 MiB worst-case disk
(`5 × 10 MiB`) is trivial on any dev machine.

### D9 — Five real-subprocess integration tests

Added to `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
(or a new sibling `test_service_eviction.py` if the existing file
would balloon past ~600 lines). All five use the
`_service_env(tmp_path)` subprocess fixture from the
service-lifecycle-tests ADR: real subprocess, ephemeral port,
real GPU, real Qdrant, real embedding model. No mocks, patches,
stubs, fakes, or skips — per the project test mandate.

- **`test_idle_ttl_evicts_quiescent_slots`** — start service with
  `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS=2`,
  `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS=4`. Seed projects A and B by
  calling `search_vault` against two temp vault roots with a
  single markdown file each. `list_projects` shows 2. Sleep 3s.
  Call `search_vault` for a third project C. Assert `list_projects`
  shows only C, and C's `idle_seconds < 1.0`.

- **`test_lru_cap_evicts_oldest`** — `SERVICE_MAX_PROJECTS=2`,
  `SERVICE_IDLE_TTL_SECONDS=0`. Hit A, hit B, hit C. Assert
  `list_projects` shows B and C only; A was evicted by the
  admission sweep.

- **`test_evict_busy_returns_busy`** — hit A to prime, then start
  a long-running concurrent `search_vault` against A in a thread
  (using a large-corpus vault fixture to stretch rerank time). In
  the main thread, immediately call `evict_project(A)` while the
  search is in flight. MUST use a corpus of ≥100 vault docs so
  reranker latency stretches the busy window beyond MCP round-trip
  time. The test asserts *at least one of N* `evict_project` calls
  returned `reason="busy"` rather than asserting on a single
  timing-sensitive call. Assert no raw Qdrant crashes or
  segfaults — the refcount skip-busy discipline must prevent
  mid-use close.

- **`test_log_rotation_creates_backups`** — start service with
  `SERVICE_LOG_MAX_BYTES=4096`, `SERVICE_LOG_BACKUP_COUNT=2`,
  `VAULTSPEC_RAG_LOG_LEVEL=DEBUG`. Drive ~50 `search_vault` calls
  to push DEBUG output past several rotation thresholds. MUST
  call `handler.flush()` after each batch of log records (or use
  `os.fsync(handler.stream.fileno())`) to make rollover
  deterministic on Windows. Poll for up to 2 seconds for rotated
  files. Assert `service.log`, `service.log.1`, `service.log.2`
  all exist; `service.log.3` does NOT; `service.log` contains
  recent-timestamp lines.

- **`test_log_rotation_post_rollover_writes_to_active`** — the
  Windows FD re-`dup2` regression guard. After forcing one
  rollover via a small rotation-trigger call, write additional
  bytes through a debug logger and assert the new bytes land in
  `service.log` (the active file), NOT in `service.log.1`. This
  is the ONLY test that asserts D1's re-`dup2` invariant
  directly; without it, a regression that reverts
  `DaemonRotatingFileHandler` to plain `RotatingFileHandler`
  would silently pass every other rotation test.

### D10 — Out of scope

Explicitly deferred to future work; not addressed by this ADR:

- Background sweeper thread for strict idle reclamation with zero
  traffic. If users need it, they can `service stop`.
- Per-project idle TTL overrides (e.g., pin a high-priority
  project). Global config only for beta.
- Signal-driven manual rotation (`SIGHUP` on Unix). Rotation is
  fully automatic from size thresholds.
- A shared file-logging rotation primitive in `vaultspec-core`.
  Optional core enhancement, tracked separately.
- Making the `close_all()` 5-second drain deadline configurable.
- Operator auth / ACL on the new admin MCP tools. The current
  service has no auth boundary anywhere (MCP streamable-http is
  localhost-only), and adding one for these two tools alone would
  create an inconsistent surface.

## Rationale

The decision pattern that ties D1–D10 together is: keep the
smallest amount of state under the smallest number of locks, reuse
existing teardown paths verbatim, and pick defaults that fix the
leak without requiring user action. D3–D4 (lease + skip-busy +
lazy sweep + LRU admission) cover eviction synchronization with
zero background threads and zero new lock types; they piggyback
on the existing `_lock` and existing `close_project` teardown.
D1 (child-side `DaemonRotatingFileHandler`) is the only option
that survives the parent-exits-immediately constraint and the
Windows FD-dup trap simultaneously. D5 collapses an orphaned
parallel cache in `api.py` that would otherwise defeat every
other decision. D7 reuses the existing MCP-as-admin-transport
pattern rather than introducing a second wire. D8 ships
conservative-on defaults because this release IS the beta gate
and there is no deployed user base to surprise. Each decision
traces back to a specific research section, and each picks the
simpler option in every fork the research raised.

## Consequences

**Positive.**

- `ServiceRegistry._projects` is bounded in both dimensions: time
  (idle TTL) and count (LRU cap). File handles, Qdrant segments,
  and graph caches no longer accumulate unboundedly.
- `service.log` is bounded to `service_log_max_bytes × (service_log_backup_count + 1)`
  (default 60 MiB). Disk exhaustion from DEBUG-level logging is
  no longer a risk.
- The service lifecycle becomes observable: `list_projects` gives
  operators a structured view of per-project idle time, refcount,
  and last-access; `evict_project` gives them a surgical cleanup
  primitive.
- `api.py` becomes a thin facade over `ServiceRegistry.lease`,
  eliminating a parallel cache and a class of
  two-caches-one-store correctness hazards.
- Graceful `close_all()` drain prevents in-flight requests from
  seeing a closed Qdrant store during service shutdown.

**Negative.**

- The hot path in `get_project` (now `lease`) must always take
  `_lock`, where the current implementation has a lock-free fast
  path for the cache-hit case. Benchmark impact: dict get + two
  int writes + a small `_sweep_idle` scan — sub-microsecond at
  the 16-slot bound, negligible compared to the ~10 ms embedding
  - ~20 ms hybrid search that follows. The research
    unexpected-findings bullet 1 flagged this explicitly.
- Rollover has a microsecond-scale window in which a third-party
  raw stdout write can land in `service.log.1` instead of the
  new active log. Python-logging-formatted writes are protected
  by the handler's `RLock`; only raw C-level writes from native
  extensions are at risk, and only during the narrow window
  between `super().doRollover()` and the re-`dup2` calls.
- LRU admission can race with bursty traffic: a fresh request for
  a new root can be refused with `RegistryFullError` if all
  existing slots are busy. Operator-visible, recoverable by
  retry, but a surprising error for the first offender.
- Lazy sweep means a quiescent service with zero traffic keeps
  stale slots alive indefinitely. Acceptable because idle slots
  cost only file handles and graph memory — no CPU, no GPU, no
  I/O. If traffic resumes, the next `lease` call evicts them.
- The early-startup window in the child (between the parent's
  `dup2`-on-spawn and the handler install in `main()`) is covered
  by the parent's append-mode FD, but if the child crashes
  before `main()` runs, all pre-crash output lands in the
  pre-rotation log and the rotation count never kicks in. The
  research recommends a tiny early "service startup" log write
  immediately before handler install as a liveness probe.

## Alternatives Considered

- **Parent-side pipe + rotator thread.** Rejected because the
  parent CLI exits immediately after `_spawn_service`; a rotator
  thread would die with the parent.
- **External `logrotate` / Windows Task Scheduler.** Rejected as
  a cross-platform packaging nightmare with no structured
  in-package story.
- **Core-level shared rotating file handler in
  `vaultspec-core.logging_config`.** Rejected for this release
  because it would gate #45 on a core release and force every
  core consumer to carry daemon-only machinery. Flagged as a
  future optional enhancement.
- **RWLock for eviction synchronization (evictor=write,
  callers=read).** Rejected: no stdlib RWLock, rolling one is
  error-prone, and refcount + skip-busy delivers the same
  invariant with simpler semantics.
- **Background sweeper thread.** Rejected for alpha-scale
  complexity budget — shutdown coordination, lock discipline,
  and no user-facing benefit at a 16-slot bound.
- **Sibling `dict[Path, float]` for `last_access` outside
  `ProjectSlot`.** Rejected; storing timestamps on the slot wins
  on locality and keeps the eviction invariant inside one data
  structure under one lock.
- **Starlette `/admin/projects` route alongside `/health` and
  `/mcp`.** Rejected: second transport, second probe path in the
  CLI, second auth surface to worry about later. The existing
  MCP tool pattern already covers every other admin-ish operation.
- **Signal-file IPC (`evict.trigger` on disk watched by the
  service).** Rejected: fragile on Windows, platform-divergent,
  no structured response.
- **Blocking LRU admission with a timeout** instead of raising
  `RegistryFullError`. Rejected for deadlock surface and
  no-benefit-at-alpha-scale; rejection is cleaner operator UX.
- **`rotator` callback on `BaseRotatingHandler` rather than
  subclassing.** Workable but splits the re-`dup2` logic from
  the handler's own `self.stream` swap; subclassing keeps both
  atomic under the same `RLock`.

## Compliance / Verification

- The five integration tests in D9 run as
  `@pytest.mark.subprocess_gpu` and MUST pass end-to-end against
  real GPU, real Qdrant, real subprocess. No mocks, no skips,
  no patches, no fakes.
- `ruff check` MUST report zero violations on all modified files.
- `mypy` (or the project's configured type checker) MUST report
  zero errors on all modified files. No `# type: ignore` escape
  hatches are accepted.
- Manual smoke: `vaultspec-rag server service start` followed by
  `vaultspec-rag service projects list` (against two distinct
  seeded roots) and `vaultspec-rag service projects evict <root>`
  MUST produce the expected rich-table and single-line output.
- Pre-commit hooks MUST pass on every modified file.

## Open Questions Resolved

The research phase listed five open questions. Their answers
are recorded here so the plan phase does not re-open them.

- **Lease API shape — raw slot + paired release, or context
  manager?** Context manager (`with registry.lease(root) as slot`),
  with `peek_project` as the non-leasing accessor for watcher
  wiring and lifespan setup. Safer invariant, and forced by the
  fact that `_ensure_watcher` must NOT participate in refcount.

- **Watcher refcount interaction — does a live watcher pin a
  slot as busy?** No. Watchers are installed via `peek_project`
  and do not bump `ref_count`. Each `incremental_index` callback
  the watcher fires acquires its own short-lived `lease` so that
  concurrent eviction during indexing is refcount-protected.
  Safe because Task #43's atomic metadata writes
  (`write-to-.tmp + os.replace`) survive watcher cancellation
  mid-index.

- **`api.py._engine` cache status — was it already collapsed?**
  No. Direct source inspection confirmed `_engine` is still a
  single-slot parallel cache holding its own `VaultStore`,
  `VaultSearcher`, indexers, and `GraphCache`. This ADR mandates
  its removal in execution Phase 1 and routes every `api.py`
  facade function through `ServiceRegistry.lease`. Details in D5.

- **Admission backpressure vs rejection.** Rejection with a
  clear `RegistryFullError` surfaced as a structured MCP error.
  Blocking-with-timeout was rejected for deadlock surface.

- **Windows stray-bytes window during rollover.** Accepted as
  documented. A lock-and-flush dance across `dup2` would add
  complexity for a window bounded to rollover events (a few per
  day) that only affects raw C-level writes. Python-logging
  writes are already protected by the handler's `RLock`.

## Migration notes

No migration tooling is required. Backwards compatibility is
guaranteed because existing service config files lack all four
new keys, so the `VaultSpecConfigWrapper` defaults apply and
eviction kicks in silently at 30 minutes idle / 16 projects
max / 10 MiB × 5 log rotation. There is one user-visible
behavioral change: a service that has been running idle for more
than 30 minutes against a project will evict that project on
the next request, causing a one-time cold-start latency spike
as the slot is recreated. Operators who need the pre-beta
behavior can set `service_idle_ttl_seconds=0` and
`service_max_projects=0` in their config, which disables both
eviction axes. This override is documented in the release notes
that accompany the beta bump.

Existing running services that started under the alpha binary
do not need to be restarted until the new binary is installed —
the change is a code-level upgrade, not a state-file format
change. `status_dir` contents (`status.json`, `service.log`)
remain format-compatible. On first start of the new binary,
the existing `service.log` is adopted by the
`DaemonRotatingFileHandler` and will be rotated in place from
that point forward; any pre-existing oversized `service.log`
is NOT retroactively trimmed, consistent with
`RotatingFileHandler` semantics.

## References / related

- `2026-04-12-store-eviction-log-rotation-research` — the phase-1
  research document that every decision above traces back to.
- `2026-04-02-service-graph-adr` — established `ServiceRegistry`,
  per-root locks, `close_project` / `close_all`,
  `_on_close_project` watcher teardown callback, and the explicit
  D6 / consequences-list deferral that this ADR discharges.
- `2026-04-05-service-lifecycle-tests-adr` — established the
  subprocess + ephemeral-port + `_service_env(tmp_path)` fixture
  pattern that the five new integration tests must reuse.
