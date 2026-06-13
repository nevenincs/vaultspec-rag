---
tags:
  - '#research'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-adr]]'
  - '[[2026-04-05-service-lifecycle-tests-research]]'
---

# `store-eviction-log-rotation` research: beta gates #45

Phase-1 research for issue #45. The service-graph ADR explicitly deferred two
concerns to beta: (a) unbounded `ServiceRegistry._projects` growth — no idle
TTL, no LRU cap, manual `service stop` is the only reset — and (b) unbounded
`service.log` growth in append mode. Both must be resolved before beta. This
document gathers options, spells out the Windows FD gotcha for rotation, and
recommends a concrete direction for the upcoming ADR.

## Context & problem statement

Grounded in the current code (`src/vaultspec_rag/service.py`,
`src/vaultspec_rag/cli.py:1221-1260`, `src/vaultspec_rag/mcp_server.py:93-145`):

- `ServiceRegistry._projects: dict[Path, ProjectSlot]` grows monotonically.
  Every new `get_project(root)` call adds a `VaultStore` (Qdrant local client
  holding file locks), a `VaultSearcher`, two indexers, and a `GraphCache`.
  Nothing prunes the dict except `close_project(root)` (only called by an
  explicit MCP request path — which does not exist today) and `close_all()`
  (lifespan shutdown). In a long-lived service visited by multiple Claude
  agents over weeks, this is an unbounded leak of file handles and Qdrant
  segments. VRAM is NOT affected (models are shared) — the leak is disk,
  file descriptors, and in-memory graph caches.

- `service.log` is opened in append mode by the PARENT CLI in
  `_spawn_service` (`cli.py:1239`) as `open(log_path, "a", encoding="utf-8")`.
  The parent passes that FD as `stdout` and dups it for `stderr`, then closes
  its own copy. The child inherits the two FDs but holds NO `logging.Handler`
  pointed at that file — the child's own stderr RichHandler (installed by
  `vaultspec_core.logging_config`) writes to `sys.stderr`, which IS the
  redirected FD. Therefore the log file collects three streams: child
  stdout prints, uvicorn/starlette stderr log lines, and RichHandler output.
  Nothing rotates it. A service running with `VAULTSPEC_RAG_LOG_LEVEL=DEBUG`
  across a big reindex will fill a disk.

- `VaultSpecConfigWrapper` already has `status_dir` and `log_file` keys
  (`config.py:78-79`). The log path is resolved in `cli.py:_log_file()` as
  `{status_dir}/{log_file}`, default `~/.vaultspec-rag/service.log`.

- The service-graph ADR D6 "Store cleanup" paragraph:
  *"deferred to beta. Alpha uses manual service stop + restart to clear all
  stores. No unbounded accumulation risk at alpha scale."*
  And the Consequences section's final bullet: *"Deferred concerns: log
  rotation for service.log (beta) ... Store idle timeout / eviction."*
  Both are exactly what #45 must now decide.

## Prior art

- **Service graph ADR (2026-04-02)** established `ServiceRegistry`, global
  `_lock`, per-root locks, `get_project` / `close_project` / `close_all`,
  and a `_on_close_project` callback that stops the filesystem watcher
  before the store closes. Eviction MUST reuse `close_project()` verbatim
  so watcher teardown ordering is preserved.

- **Service lifecycle tests ADR (2026-04-05)** established the subprocess

  - ephemeral-port pattern in
    `src/vaultspec_rag/tests/integration/test_service_lifecycle.py` using
    `_service_env(tmp_path)` to isolate `VAULTSPEC_RAG_STATUS_DIR`. New tests
    for #45 must layer onto the same fixture so they inherit real GPU,
    real Qdrant, and real subprocess semantics (no mocks — test mandate).

- **Round 36 audit (R36-C1)** fixed a concurrent-rebuild race inside the
  graph cache using `threading.Lock` + double-check. The same discipline
  applies here: eviction decisions MUST be atomic under `_lock`.

## Option analysis — log rotation

Three options, grounded in how `_spawn_service` currently redirects FDs.

### A1 — child-side RotatingFileHandler + `os.dup2` takeover of stdout/stderr

In the child (very early in `mcp_server.main`, before uvicorn starts):

1. Open a `logging.handlers.RotatingFileHandler(log_path, maxBytes=cfg.service_log_max_bytes, backupCount=cfg.service_log_backup_count, encoding="utf-8")`.
1. `os.dup2(handler.stream.fileno(), 1)` and `os.dup2(..., 2)`, so that
   `print()`, uvicorn access logs, and any bare writes from native libraries
   also land in the rotated file. This is the only way the parent-supplied
   append-mode FD stops being a second, unrotated writer — after `dup2` the
   parent's FD is closed and the kernel inode is the same one the handler
   owns.
1. Install the handler on the root logger so RichHandler output is also
   routed through it (alternatively: leave RichHandler on stderr, which
   after dup2 IS the rotated file — simpler, no double-logging).

**The Windows gotcha.** `RotatingFileHandler.doRollover()` on Windows does
(roughly): `self.stream.close(); os.rename(base, base+".1"); self.stream = self._open()`.
That rename CAN succeed on modern Python because the handler closes its own
stream first. But the dup'd FDs 1 and 2 are SEPARATE kernel references to
the same original inode. Closing the Python file object does NOT close
those FDs. On Windows, `os.rename` on an open file can fail with
`PermissionError` *if any open handle lacks `FILE_SHARE_DELETE`*.
Python's `_open` uses `io.open` which on Windows uses `CreateFileW` with
`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` — so the rename
is permitted even though FDs 1 and 2 still reference the old inode. This
is the critical detail: **the rename will work, but FDs 1 and 2 will keep
writing to the now-renamed `service.log.1` file until they are re-dup'd**.
Effectively the FIRST rollover "sticks" stdout/stderr on the
`.1` file and all subsequent rollovers only rotate the handler's own
stream, not the dup'd FDs. The backup count silently loses track.

**Fix.** Subclass `RotatingFileHandler` and override `doRollover` to
re-`dup2` FDs 1 and 2 onto the freshly-opened new stream AFTER the parent
rollover runs:

```
class DaemonRotatingFileHandler(RotatingFileHandler):
    def doRollover(self):
        super().doRollover()
        fd = self.stream.fileno()
        os.dup2(fd, 1)
        os.dup2(fd, 2)
```

Alternatively use the `rotator` callback (documented in the
`BaseRotatingHandler` API — `rotate(source, dest)`) plus a post-hook.
Subclassing is simpler and keeps the re-dup atomic with the handler's own
`self.stream` swap. The `DaemonRotatingFileHandler` runs in the child
process, under the root logger's lock, so there is no thread race.

There is ONE remaining window: if another thread writes to FDs 1/2 via a
C-level `write(2)` during the microsecond between `super().doRollover()`
and the second `dup2`, those bytes land on the renamed file. For our
workload (uvicorn + RichHandler + occasional prints) this is acceptable
— the Python logging lock serializes handler writes, and the stray-bytes
window is bounded to rollover events. Document it as a known, benign edge.

### A2 — parent-side rotator thread + pipe

Parent spawns child with `stdout=PIPE, stderr=STDOUT`, then runs a
background thread reading the pipe and writing to a `RotatingFileHandler`.
**Not viable.** The parent CLI process exits immediately after
`_spawn_service` returns (that is the whole point of detached spawn). The
rotator thread would die with it. Keeping the parent alive defeats the
dmypy pattern. Rejected.

### A3 — external logrotate / Task Scheduler

Cross-platform nightmare. Requires user-side config, not in-package.
Rejected.

**Recommendation: A1 with a custom `DaemonRotatingFileHandler` subclass
that re-`dup2`s 1 and 2 after every rollover.** Implement in a new module
(e.g. `src/vaultspec_rag/service_logging.py`) and call it from
`mcp_server.main()` BEFORE `uvicorn.run`. The parent CLI path in
`_spawn_service` keeps passing an append-mode FD exactly as today — the
child immediately replaces it via `dup2`, the parent's original FD is
closed (it was closed already at `log_fh.close()` on `cli.py:1258`),
and the inode that's actually rotated is the one the handler opened.

### Core vs rag placement

Rotation belongs in **vaultspec-rag**, not vaultspec-core. Core's
`logging_config` installs a stderr RichHandler for one-shot CLI and MCP
stdio tooling; it has no concept of a persistent daemon log file, and
its consumers (CLI commands, tests) should not pay the cost of a
rotating file handler. A future core enhancement — optional file
handler with rotation knobs — would be welcome but must not block #45.

## Option analysis — eviction synchronization

Current state recap: `_projects: dict[Path, ProjectSlot]` under `_lock`;
per-root locks in `_root_locks`; every request path in `mcp_server.py`
goes through `_registry.get_project(root)` (verified by grep —
`mcp_server.py:212,552,606,651,744,791,840` — plus `api.py` and the
watcher constructor). No `ProjectSlot` mutability for timestamps yet,
no refcount.

### Where to store `last_access`

**Recommend: on `ProjectSlot`.** The dataclass is already mutable
(default `@dataclass` without `frozen=True`), so adding
`last_access: float = 0.0` (monotonic) and `ref_count: int = 0` is
surgical. A sibling `dict[Path, float]` in the registry is possible
but splits the invariant across two data structures under one lock.
On-slot wins on locality.

### Where to touch `last_access`

**Recommend: inside `get_project()` under `_lock`, immediately before
returning any slot** (both the cache-hit fast path and the create path).
All request paths funnel through `get_project()`, so this is the single
chokepoint — verified by grep for `_projects[`: no direct dict access
outside `service.py`. The fast path currently returns `self._projects.get(root)`
BEFORE taking `_lock`, which is a correctness shortcut the ADR must
address: to update a timestamp and increment a refcount atomically the
fast path MUST take `_lock`. Benchmark-wise, `_lock` is held for
microseconds (a dict get and two field writes), so the hit is negligible
compared to the embedding/search path that follows.

### Eviction mechanism — three candidates

- **(i) Lazy sweep inside `get_project()`**: every call scans `_projects`,
  evicts any slot with `idle > TTL AND ref_count == 0`. O(n) where n is
  bounded by `service_max_projects` (small — 16). Zero background threads.
  Runs only when there's live traffic, which is exactly when eviction
  decisions matter.
- **(ii) Background sweeper thread**: a daemon thread wakes every N seconds
  and sweeps. More responsive at zero traffic (evicts a stale project even
  if nobody ever calls again), but adds a shutdown-coordination problem
  with `close_all()` and must not deadlock with `_lock`. The alpha service
  already has enough thread/lifespan complexity.
- **(iii) Hybrid — lazy sweep plus opportunistic eviction on admission**:
  `get_project()` sweeps on every call; additionally, when creating a new
  slot it checks `len(_projects) >= max_projects` and LRU-evicts the
  oldest evictable slot to make room.

**Recommend (iii).** It is the simplest correct design: no background
thread, no shutdown dance, eviction is deterministic on traffic, and the
LRU cap gives a hard upper bound. Idle-only eviction (no traffic, stale
project lingers forever) is a non-issue in practice — when the service
is idle, holding a `VaultStore` costs nothing but a few file handles;
when traffic resumes, the sweep fires. If users want strict idle
reclamation, they can `service stop`.

### Safety while a request is in flight

A slot must not be closed mid-search. `slot.store.close()` invalidates
the Qdrant client; an in-flight `search_vault` would crash with an obscure
error. Three shapes:

- **Refcount + context manager** (`slot.acquire()` / `slot.release()`,
  eviction only considers slots with `ref_count == 0`). Requires every
  consumer to wrap slot use in `with slot.lease(): ...`. Cleanest
  invariants; largest blast radius (every `get_project` call site in
  `mcp_server.py` gets a context manager).
- **RWLock** (evictor takes write, callers take read). Overkill;
  pure-Python RWLocks aren't in the stdlib and rolling one is error-prone.
- **Skip-busy** (evictor only touches `ref_count == 0` slots; busy slots
  are deferred to the next sweep). Non-blocking, simple.

**Recommend refcount + skip-busy + non-blocking LRU admission.** The
refcount is incremented inside `get_project()` while `_lock` is held,
*before* returning — so the caller receives a slot that is guaranteed to
still be alive when they touch it. Callers decrement via a returned
lease context manager (or a `release_project(root)` call). The evictor
sweep sees any non-zero refcount and simply skips that slot. This
avoids the R36-C1-class race: all eviction decisions happen under
`_lock` and only act on definitionally quiescent slots.

Critically, `close_project()` as an admin-forced action is a different
code path: if `ref_count > 0` it should return
`{evicted: False, reason: "busy", ref_count: N}` rather than block. The
CLI surfaces that clearly; the operator retries.

### LRU cap enforcement

When `get_project()` creates a new slot and `len(_projects) >= max_projects`:
pick the slot with the smallest `last_access` that has `ref_count == 0`
and call `close_project(root)` on it (so the watcher-stop path runs).
If NO slot is evictable (all busy), raise a clear `RuntimeError`
surfaced as an MCP error — this is operator-visible and recoverable
by retry. Blocking-with-timeout was considered and rejected: it
introduces deadlock surface for little benefit at alpha scale.

### Interaction with existing `_on_close_project` watcher callback

`close_project(root)` already stops the watcher via
`_on_close_project(root)` before popping and closing the store
(`service.py:285-295`). Eviction reuses this path exactly — no new
teardown code. The lazy sweep calls `close_project()` with the global
lock RELEASED (since `close_project` takes it internally), so the
sweeper must drop `_lock` between "identify victims" and "call
`close_project`". The victim list is collected under `_lock`; the
actual teardown runs outside it. Any concurrent request for the same
root during the gap loses the race and creates a fresh slot — this is
benign (the old slot was already flagged for eviction under its own
decision point).

### Default config values — opt-in vs opt-out

Two schools:

- **Opt-in (default = 0 / disabled)**. Zero behavior change for current
  deployments, users who care enable explicitly. Safest from a
  "surprise regression" standpoint.
- **Conservative-on (30 min TTL, 16 max projects)**. Ships the feature
  actually enabled so users benefit without config.

**Recommend: conservative-on** for both knobs, because:

1. The service-graph ADR is still pre-beta; #45 IS the beta gate. There
   is no large installed base to surprise.
1. The leak this fixes (file handles, graph caches) is real and silent.
   Requiring opt-in means most users never enable it and the leak ships.
1. 30 min idle TTL is long enough that no active workflow triggers it
   accidentally; 16 projects is well above the 1–3 typical developer
   working set.

The knobs remain configurable, and `service_idle_ttl_seconds=0` is
honored as "disabled" for users who want the old behavior.

## Option analysis — CLI `service projects` transport

`service projects list` and `service projects evict <root>` must talk to
a running service.

- **(D1) New MCP tools** `list_projects` / `evict_project` on the existing
  FastMCP streamable-http server. All existing admin-ish tools
  (`get_index_status`, `reindex_vault`, `reindex_codebase`, `get_code_file`)
  already follow this pattern. Task #19 `_try_mcp_search` proves the
  CLI-as-MCP-client fast path works for tool invocation. One transport,
  stdio and HTTP both get it.
- **(D2) Starlette admin route** `/admin/projects` alongside `/health` and
  `/mcp`. Clean separation, but a second transport the CLI must probe and
  a second auth boundary to worry about later. The `/health` endpoint is
  already the exception we tolerate because MCP has no natural "health
  ping" concept; eviction, by contrast, is exactly a tool call.
- **(D3) IPC via signal file**. Rejected — fragile on Windows, platform-
  divergent, no structured response.

**Recommend D1.** Two new MCP tools:

**`list_projects(project_root: str | None = None) -> dict`**
Returns:

```
{
  "projects": [
    {
      "root": "C:/code/foo",
      "last_access_iso": "2026-04-12T10:14:33Z",
      "idle_seconds": 42.1,
      "ref_count": 0,
      "document_count": 1234  # optional, from store
    },
    ...
  ],
  "max_projects": 16,
  "idle_ttl_seconds": 1800
}
```

`project_root` is accepted (and ignored) for signature parity with the
other tools — admin tools are global, not project-scoped.

**`evict_project(root: str) -> dict`**
Returns:

```
{"evicted": true,  "root": "C:/code/foo", "reason": null}
{"evicted": false, "root": "C:/code/foo", "reason": "busy",     "ref_count": 2}
{"evicted": false, "root": "C:/code/foo", "reason": "not_found"}
```

The tool resolves `root` via `Path(root).resolve()` before lookup (same
discipline as `get_project`). Busy slots are skipped non-blockingly.

Corresponding CLI:

- `vaultspec-rag service projects list [--port N]` — fast-path via
  `_try_mcp_client_call("list_projects")` mirroring `_try_mcp_search`.
- `vaultspec-rag service projects evict <root> [--port N]` — same, for
  `evict_project`. Exit code 0 on success, non-zero on busy/not_found
  with a clear message.

## Config keys

Four new keys in `_RAG_DEFAULTS` on `VaultSpecConfigWrapper`
(`config.py:73-91`) with matching `EnvVar` enum entries and
`_ENV_OVERRIDE_MAP` wiring:

| Key                        | Default    | Env var                               | Notes                          |
| -------------------------- | ---------- | ------------------------------------- | ------------------------------ |
| `service_idle_ttl_seconds` | `1800`     | `VAULTSPEC_RAG_SERVICE_IDLE_TTL`      | 0 disables idle eviction       |
| `service_max_projects`     | `16`       | `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`  | 0 disables LRU cap             |
| `service_log_max_bytes`    | `10485760` | `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES` | 10 MiB                         |
| `service_log_backup_count` | `5`        | `VAULTSPEC_RAG_SERVICE_LOG_BACKUPS`   | 5 × 10 MiB = 50 MiB worst case |

All four belong in rag, not core, because the service daemon is a
rag concept. Core remains project-agnostic.

## Testing strategy

Must follow the existing integration pattern in
`src/vaultspec_rag/tests/integration/test_service_lifecycle.py`:
subprocess + ephemeral port + `_service_env(tmp_path)`. No mocks, no
skips, real GPU, real Qdrant. All new tests marked
`@pytest.mark.subprocess_gpu`.

**Test 1 — eviction on idle TTL.** Start service with
`VAULTSPEC_RAG_SERVICE_IDLE_TTL=2`, `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS=4`.
Seed projects A and B by calling `search_vault` MCP tool against two
distinct temp vault roots populated with a single markdown file each.
`list_projects` → 2 entries. `time.sleep(3)`. Call `search_vault` for
project C. `list_projects` → only C present; A and B evicted. Assert
`idle_seconds < 1.0` for C.

**Test 2 — LRU cap.** `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS=2`,
`VAULTSPEC_RAG_SERVICE_IDLE_TTL=0` (disabled). Hit A, hit B, hit C.
Assert `list_projects` → {B, C}; A evicted by admission sweep.

**Test 3 — in-flight safety.** Hit project A in one thread (or use a
concurrent MCP call issued via `anyio.create_task_group`), fire
`evict_project(A)` from a second thread as close to simultaneously as
possible. Assert ONE of:
(a) `evicted=True` AND the in-flight search either completed successfully
before eviction or raised a clean error (not a segfault / raw Qdrant
crash) — because refcount skip-busy must prevent mid-use close.
(b) `evicted=False, reason="busy", ref_count>=1`.
Repeat in a tight loop (say 20 iterations) to exercise the race window.
If we ever see a raw crash, the refcount discipline is broken.

**Test 4 — log rotation.** Start service with
`VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES=4096`,
`VAULTSPEC_RAG_SERVICE_LOG_BACKUPS=2`,
`VAULTSPEC_RAG_LOG_LEVEL=DEBUG`. Issue enough `search_vault` calls (say
50\) to push DEBUG output past several rotation thresholds. Assert
`service.log`, `service.log.1`, `service.log.2` all exist;
`service.log.3` does NOT; each rotated file ≤ ~4 KiB + small overrun;
`service.log` contains recent-timestamp lines. The Windows-specific
assertion: the combined byte count of rotated files should be at least
`backup_count * max_bytes * 0.5` — i.e. stdout/stderr actually followed
the dup2 into the rotated files rather than pinning the first rollover.

**Test 5 — Windows FD re-dup2 regression.** On Windows only
(`sys.platform == "win32"`), after triggering one rollover, write
directly to `sys.stdout` in the child (via a small `debug_echo` MCP
tool added for this purpose OR by invoking a path that prints) and
assert the bytes land in the NEW `service.log`, not in `service.log.1`.
This is the actual guarantee that `DaemonRotatingFileHandler.doRollover`
re-dups FDs 1/2. Without this test, a regression that reverts to plain
`RotatingFileHandler` would silently pass all other tests.

**Cross-platform flake note.** Test 4 is the likely flaker on Windows
because rollover timing depends on buffering. Mitigations: flush the
handler explicitly after each search, use a very small `max_bytes` so
buffering never holds a full generation, and poll the filesystem for
rotated files with a 2s deadline rather than asserting immediately.

## Recommended direction (summary)

- **Rotation**: child-side `DaemonRotatingFileHandler` subclass that
  overrides `doRollover` to re-`os.dup2` FDs 1 and 2 onto the fresh
  stream. Installed in `mcp_server.main()` before uvicorn boot.
  Parent-side `_spawn_service` unchanged.
- **Eviction**: `ProjectSlot` gains `last_access: float` and
  `ref_count: int`. `get_project()` updates both under `_lock`, runs a
  lazy sweep of idle slots, and LRU-evicts on admission when the cap
  is reached. `close_project()` is reused verbatim for teardown.
  Skip-busy discipline — evictor never touches `ref_count > 0` slots.
- **Transport**: two new MCP tools `list_projects` and `evict_project`.
  CLI `service projects list` / `service projects evict <root>` use
  the existing MCP fast-path pattern.
- **Config**: four new keys with `VAULTSPEC_RAG_` env overrides.
  Defaults on (30 min TTL, 16 projects, 10 MiB × 5 backups).
- **Tests**: five subprocess_gpu integration tests covering idle TTL,
  LRU cap, in-flight safety, rotation, and Windows FD re-dup.

## Open questions for the ADR phase

- **Lease API shape.** Does `get_project` return a raw `ProjectSlot` (and
  every caller must remember `release_project(root)`), or does it return
  a context manager (`with registry.project(root) as slot: ...`)? The
  latter is strictly safer but touches every call site in `mcp_server.py`
  (8 sites). The ADR should pick.
- **Watcher refcount interaction.** The watcher lives inside the slot's
  lifetime and holds a reference to `slot.vault_indexer` via closure
  (`mcp_server.py:223-232`). Does a live watcher count toward `ref_count`?
  If yes, nothing is ever evictable. Proposal: watchers do NOT hold
  refcount; eviction's `close_project` calls `_on_close_project` which
  cancels the watcher task cleanly. But the ADR must confirm that
  cancelling a watcher that is mid-`incremental_index()` is safe given
  Task #43's atomic metadata writes.
- **`api.py` engine cache interaction.** `api.py` currently keeps its own
  `_engine` global keyed by resolved path. Does eviction invalidate that
  cache, or does `api.py` become a thin wrapper around
  `ServiceRegistry.get_project`? The service-graph ADR said the latter
  was the goal — confirm it has already happened or schedule it here.
- **Admission backpressure vs rejection.** Chose rejection above. The
  ADR should re-confirm once the operator UX is written down — a reject
  on a fresh project root is user-visible and needs a clear error
  message from the MCP tool.
- **Windows stray-bytes window.** Accept as documented, or invest in
  a lock-and-flush dance (acquire root logger lock across `dup2`)?
  Recommend accept; flag it as a known edge in the ADR consequences.

## Unexpected findings from the source grounding

- `get_project()` has a lock-free fast path (`service.py:189-191`) that
  reads `_projects.get(root)` without taking `_lock`. Adding timestamp +
  refcount updates REQUIRES moving that read under `_lock` — a small
  contention regression on the hot path that the ADR must acknowledge.
  (Benchmark: dict get + two int writes is sub-microsecond, negligible
  next to the ~10 ms embedding + ~20 ms hybrid search that follows.)
- `_ensure_watcher` in `mcp_server.py:193-235` calls `get_project(root)`
  WITHOUT any release — the watcher thread is not a "request" in the
  refcount sense. If the ADR chooses "every `get_project` bumps
  refcount" as its uniform rule, `_ensure_watcher` must NOT use
  `get_project` for that purpose — it needs a `peek_project()` that
  does not bump. This is the cleanest confirmation that the lease API
  must be an explicit opt-in (`with registry.lease(root) as slot`), not
  a side effect of `get_project`.
- `close_all()` iterates `_projects` while holding `_lock` and calls
  `slot.store.close()` inside (`service.py:313-318`). That is fine
  today because shutdown is single-threaded, but if eviction adds a
  skip-busy path, `close_all()` must also skip-busy OR force-close with
  a timeout. Document the chosen shutdown semantics explicitly.
- The parent's `log_fh.close()` on `cli.py:1258` is a pre-existing
  subtle correctness bet: the child must have its own duplicate of the
  FD before the parent closes the Python file object, otherwise the
  first child write races against the parent's finalizer. `subprocess`
  handles this by calling `os.dup2` in the child between `fork` and
  `exec` on Unix, and by setting `HANDLE_FLAG_INHERIT` on Windows —
  both are correct, but the A1 recommendation (child replaces FDs 1/2
  at startup) means the parent-supplied FDs only need to survive
  long enough for the child to run a few lines of Python before
  `dup2` takes over. Acceptable, but note that if the child crashes
  before installing the handler, all log output before that crash is
  lost — consider a tiny early write of "service startup" before the
  handler install to prove the FDs are live.
