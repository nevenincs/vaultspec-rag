---
tags:
  - '#plan'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-06-30'
related:
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
  - '[[2026-04-12-store-eviction-log-rotation-research]]'
  - '[[2026-04-02-service-graph-adr]]'
---

# `store-eviction-log-rotation` `phase-1` plan | (**status:** `approved`)

Reviewer trail: Reviewed by: 2 parallel reviewers (code-fit/integration risk, tests/mandate compliance), 2026-04-12; all critical and major findings addressed. Plan status: Approved.

Phase-1 plan for vaultspec-rag issue #45 — bounded multi-tenant service with
evictable project slots and rotated daemon logs. Implements the ten decisions
recorded in the accepted ADR (`2026-04-12-store-eviction-log-rotation-adr.md`)
in twelve traceable steps. Every step ties back to a specific ADR decision and
is verifiable end-to-end without mocks, patches, stubs, fakes, or skips.

## Proposed changes

Two long-standing beta gates are addressed in a single feature:

- `ServiceRegistry._projects` currently grows monotonically across the lifetime
  of the daemon (`src/vaultspec_rag/service.py`). Every distinct workspace root
  visited by a search or index call allocates a `ProjectSlot` (Qdrant client,
  searcher, two indexers, graph cache, watcher). The only pruning path is the
  unreachable explicit `close_project()` and lifespan `close_all()`. This
  phase introduces a context-manager lease API with monotonic `last_access`

  - `ref_count`, a skip-busy lazy sweep, and LRU-based admission capping
    against a new `service_max_projects` knob. Eviction reuses the existing
    `close_project` / `_on_close_project` teardown path verbatim so watcher
    ordering is preserved (ADR D3, D4, D6).

- `service.log` is opened in append mode by `_spawn_service` in
  `src/vaultspec_rag/cli.py` around the `_log_file()` path (line ~1025) and
  inherited by the child as dup'd stdout/stderr. Nothing rotates it. This
  phase introduces a child-side `DaemonRotatingFileHandler` that overrides
  `doRollover` to re-`os.dup2` fds 1 and 2 onto the freshly rotated stream,
  installed by a new `install_daemon_log_rotation()` helper wired into
  `mcp_server.main()` after `configure_logging()` and before `uvicorn.run()`
  (ADR D1). Rotation lives in rag, not core (ADR D2).

The `api.py` module still owns a single-slot `_Engine` singleton parallel
to `ServiceRegistry`. This phase collapses `api.py` onto
`ServiceRegistry.lease` (ADR D5) so eviction is not silently bypassed by
facade callers, and relocates `GraphCache` from `api.py` to a new
`graph_cache.py` module (ADR D5 "GraphCache relocation"). Two new admin
MCP tools (`list_projects`, `evict_project`) plus matching
`vaultspec-rag service projects list|evict` CLI commands expose the
registry state to operators (ADR D7).

Four new config keys with `VAULTSPEC_RAG_` env overrides carry the knobs
(ADR D8) and defaults ship enabled (conservative-on: 30 min idle TTL, 16
max projects, 10 MiB × 5 log rotation).

## Non-negotiable mandates

These rules apply to every step below and to all tests introduced by this
plan. Violations block merge:

- **No mocks, no patches, no monkeypatch, no stubs, no fakes, no
  `@pytest.mark.skip`, no `pytest.skip()` calls.** Every new test must
  exercise the real subprocess, real GPU, real Qdrant path. Tautological
  tests (asserting that `x = 1; assert x == 1`) are unacceptable.
- **No `# type: ignore` escape hatches.** If ruff or the
  project's type checker (`ty`) complains, the fix is to the code,
  not the checker.
- **No silent reverts** of behavior established by the service-graph ADR
  (`2026-04-02`) — the three-level lock dance, `_on_close_project`
  callback ordering, and the shared reranker stay exactly as they are.
- **Test mandate parity with service-lifecycle tests ADR** — new
  integration tests layer onto the existing `_service_env(tmp_path)`
  subprocess fixture in `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

## Tasks

Twelve ordered steps. Every step is one commit (see "Commit cadence"
below). Steps 1–9 implement the behavior; step 10 adds the integration
tests; steps 11–12 cover verification.

### Step 1 — Config keys and `EnvVar` members

**Goal.** Extend `VaultSpecConfigWrapper` with the four ADR D8 knobs so
that every later step can read `cfg.service_idle_ttl_seconds`,
`cfg.service_max_projects`, `cfg.service_log_max_bytes`, and
`cfg.service_log_backup_count` without further wiring.

**Files touched.**

- `src/vaultspec_rag/config.py`

**Changes.**

- Add four members to `EnvVar` (around the existing enum block at
  `config.py:17-39`): `SERVICE_IDLE_TTL_SECONDS`, `SERVICE_MAX_PROJECTS`,
  `SERVICE_LOG_MAX_BYTES`, `SERVICE_LOG_BACKUP_COUNT`, each with the full
  `VAULTSPEC_RAG_SERVICE_*` string per the ADR D8 table.
- Extend `_ENV_OVERRIDE_MAP` (`config.py:42-51`) with the four new key →
  `EnvVar` mappings.
- Extend `VaultSpecConfigWrapper._RAG_DEFAULTS` (`config.py:73-91`) with
  four new keys in the exact types the ADR specifies: `1800` (int),
  `16` (int), `10485760` (int), `5` (int). Types matter because
  `__getattr__`'s type coercion at `config.py:134-141` dispatches on
  `isinstance(default, int/float/bool)`.

**Tests added.**

- `src/vaultspec_rag/tests/test_config.py`: `test_service_idle_ttl_default`,
  `test_service_max_projects_default`,
  `test_service_log_max_bytes_default`,
  `test_service_log_backup_count_default`,
  `test_service_idle_ttl_env_override`,
  `test_service_max_projects_env_override`,
  `test_service_log_max_bytes_env_override`,
  `test_service_log_backup_count_env_override`. Each env override test
  sets the real env var via `os.environ` inside a `try/finally` and
  calls `reset_config()` + `get_config()` (no monkeypatch).

**Definition of done.**

- `ruff check src/vaultspec_rag/config.py` is clean.
- `uv run vaultspec-rag test src/vaultspec_rag/tests/test_config.py` is
  green with the eight new tests.
- `get_config().service_idle_ttl_seconds == 1800` on a fresh process.
- Env var `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS=60` is respected and
  coerced to `int`.

**Dependencies.** None. Step 1 is the foundation every later step reads
from.

### Step 2 — Relocate `GraphCache` to `graph_cache.py`

**Goal.** Move `GraphCache` out of `api.py` into its own module
(`src/vaultspec_rag/graph_cache.py`) to clear the way for step 5's
collapse of `api.py._engine`. This is a separate commit on purpose so
that step 5 starts from a clean base — it is also the ADR D5
"GraphCache relocation" decision.

**Files touched.**

- `src/vaultspec_rag/graph_cache.py` (new, copies `GraphCache` verbatim
  from `api.py:265-346`)
- `src/vaultspec_rag/api.py` (delete the class body at lines 265-346,
  then `from .graph_cache import GraphCache` so that existing public
  re-exports keep working)
- `src/vaultspec_rag/service.py` (update the import at line 28:
  `from .graph_cache import GraphCache`)
- `src/vaultspec_rag/watcher.py` (update the TYPE_CHECKING import at
  line 21)
- `src/vaultspec_rag/__init__.py` (the existing public re-export at
  lines 27-50 keeps its path through `api.py` for now — step 5 decides
  its final fate)
- `src/vaultspec_rag/tests/test_graph_cache.py` (update the import at
  line 19: `from vaultspec_rag.graph_cache import GraphCache`)
- `src/vaultspec_rag/tests/test_adr_regression.py` (update the two
  imports inside `TestGraphCache` methods at lines 128 and 140)

**Changes.**

- Copy `GraphCache` (class body only) from `api.py` to
  `graph_cache.py` including docstrings, the `TYPE_CHECKING` import of
  `VaultGraph`, the `threading`, `time`, `pathlib` imports, and the
  module `logger = logging.getLogger(__name__)`.
- In `api.py`, delete the class body, replace with
  `from .graph_cache import GraphCache` at the top of the module (after
  the existing imports). Leave `"GraphCache"` in `__all__` — it is a
  compat shim for this commit only; step 5 decides whether to keep it.
- Update all three non-test callsite imports (`service.py`,
  `watcher.py` TYPE_CHECKING, and `api.py._Engine.__init__` at
  line 72 which uses the local `GraphCache` by name — after the import
  rewrite it resolves to the re-exported symbol, no change needed).
- Update the two test-file imports explicitly (no wildcard imports).

**Tests added.** None new. The existing `test_graph_cache.py` (201
lines, 14 tests) and the four `test_adr_regression.py` tests under
`TestGraphCache` and `TestGraphCacheInvalidation` serve as regression
coverage for the relocation.

**Definition of done.**

- `ruff check src/vaultspec_rag/graph_cache.py src/vaultspec_rag/api.py`
  is clean.
- `grep -r "from .api import GraphCache" src/vaultspec_rag/` returns no matches except the backwards-compat
  re-export inside `api.py` itself.
- `grep -r "from vaultspec_rag.api import GraphCache" src/vaultspec_rag/tests/` returns no matches (all test files
  updated).
- `uv run vaultspec-rag test src/vaultspec_rag/tests/test_graph_cache.py src/vaultspec_rag/tests/test_adr_regression.py` is green.
- The pre-commit hook passes on all six modified files.

**Dependencies.** Step 1 (not strictly required, but the commit order
is deliberate: step 1 lands the config surface so step 2's relocation
does not conflict with `config.py` on merge).

**Critical constraint.** Step 2 MUST be a separate commit before step 5
runs. Combining them destroys the blast-radius isolation that lets
step 5 focus entirely on the `_engine` collapse without touching
`GraphCache` code.

### Step 3 — `DaemonRotatingFileHandler` and `install_daemon_log_rotation`

**Goal.** Introduce the rotating file handler subclass and its install
helper per ADR D1, but do NOT wire it into `mcp_server.main()` yet
(that is step 9, by design — the integration tests in step 10 are the
only coverage for the wiring, because a unit test would require
mocks).

**Files touched.**

- `src/vaultspec_rag/logging_config.py` (extend the thin wrapper at
  lines 1-44 with the subclass and helper)

**Changes.**

- Add `DaemonRotatingFileHandler(RotatingFileHandler)` with an
  overridden `doRollover(self) -> None` that acquires `self.acquire()`,
  calls `super().doRollover()`, then `os.dup2(self.stream.fileno(), 1)`
  and `os.dup2(self.stream.fileno(), 2)`, then releases. Exception
  handling exactly as specified in the ADR D1 code block — best-effort,
  log via `logger.exception`, re-raise. The RLock reentrancy guarantee
  (Python's `Handler.createLock()` returns a reentrant lock) is
  load-bearing and is cited in a one-line comment above the acquire.
- Add `install_daemon_log_rotation(log_path: Path, *, max_bytes: int, backup_count: int) -> DaemonRotatingFileHandler | None`. Behavior:
  idempotent (returns the existing handler if the root logger already
  has one); constructs the handler with `encoding="utf-8"`; attaches
  to the root logger; performs an initial `os.dup2` of fds 1 and 2
  onto `handler.stream.fileno()`; returns the handler.
- Export both from `__all__`.

**Tests added.**

- `src/vaultspec_rag/tests/test_logging_config.py` (new file):
  `test_daemon_rotating_handler_doRollover_re_dups_stdio` — writes
  enough bytes to a tempfile-backed handler to force one rollover,
  then verifies fd-identity via marker bytes (cross-platform).
  Verification mechanism (cross-platform): after the post-rollover
  phase, the test calls
  `os.write(1, b'__POST_ROLLOVER_MARKER__\n')` and
  `os.write(2, b'__POST_ROLLOVER_STDERR__\n')`, then reads
  `Path(log_path).read_bytes()` and asserts both markers are present
  in the active file (`service.log`), and reads
  `Path(log_path + '.1').read_bytes()` and asserts the markers are
  NOT present there. Linux-only `/proc/self/fd` introspection is
  forbidden — the marker-write approach is the ONLY portable path.
  Tests must save the original fds via
  `saved_stdout = os.dup(1); saved_stderr = os.dup(2)` at setup,
  restore via `os.dup2(saved_stdout, 1); os.dup2(saved_stderr, 2); os.close(saved_stdout); os.close(saved_stderr)` in `finally` to
  keep pytest's own captures alive.
  `test_install_attaches_to_root_logger_is_idempotent` — asserts
  exactly ONE `DaemonRotatingFileHandler` is on the root logger
  after the first `install_daemon_log_rotation()` call, AND that
  calling it a second time leaves the count at exactly one (the
  idempotency invariant). The two assertions live in the same test
  rather than being split across two tests.
- Critical: these tests run as REAL unit tests (no mocks) by writing
  to real filesystem paths under `tmp_path` and performing real
  `os.dup2` calls. The fd save/restore dance described above is NOT
  a mock — it is the only safe way to unit-test `os.dup2` behavior.

**Definition of done.**

- `ruff check src/vaultspec_rag/logging_config.py src/vaultspec_rag/tests/test_logging_config.py` is clean.
- `uv run vaultspec-rag test src/vaultspec_rag/tests/test_logging_config.py`
  is green.
- The handler's `doRollover` path is exercised at least once with a
  real rollover (max_bytes small enough that two log records force
  one rotation).

**Dependencies.** Step 1 (knobs must exist so the helper can accept
`max_bytes`/`backup_count` values that match the config surface).

### Step 4 — `ServiceRegistry` lease API with refcount and eviction

**Goal.** Grow `ServiceRegistry` into the ADR D3/D4/D6 shape: lease
context manager, `peek_project`, per-slot `last_access` +
`ref_count`, skip-busy lazy sweep, LRU admission with
`RegistryFullError`, and a graceful-drain `close_all`. This is the
largest code step and the heart of the feature.

**Files touched.**

- `src/vaultspec_rag/service.py`

**Changes.**

- `ProjectSlot` dataclass (`service.py:35-52`): add
  `last_access: float = 0.0` and `ref_count: int = 0` fields. The
  dataclass is non-frozen so mutation is valid.
- Add a new module-level exception: `RegistryFullError(Exception)`
  carrying `max_projects` as an attribute and a clear message.
- `ServiceRegistry.__init__` (`service.py:71-81`): read
  `cfg.service_idle_ttl_seconds` and `cfg.service_max_projects` into
  `self._idle_ttl_seconds: float` and `self._max_projects: int`. Add
  a `max_projects` read-only property for the MCP error shape.
- Add `def lease(self, root: Path)` as a
  `@contextlib.contextmanager` method. On enter: calls a new
  `_acquire(root)` (below) and yields the slot. On exit: calls a new
  `_release(slot)` that decrements `ref_count` under `_lock`.
- Add `def _acquire(self, root: Path) -> ProjectSlot` that performs the
  full ADR D4 "Acquire path": takes `_lock`, checks `_shutting_down`,
  does `get-or-admit-with-LRU`, updates `last_access` and `ref_count`,
  calls `_sweep_idle()` (still under `_lock`), returns the slot. The
  existing three-level lock dance from `get_project` (`service.py:186-215`)
  is preserved by moving the per-root-lock branching into a helper
  `_get_or_create_locked(root)` that runs under `_lock` (for the dict
  read) and then outside `_lock` during `_create_slot()` (for GPU init
  parallelism).
- Rename the existing public `get_project` to `peek_project` — it
  keeps the three-level lock dance, keeps returning the slot
  unchanged, but does NOT bump `ref_count` or update `last_access`.
  Callers that are non-request (watcher wiring, lifespan, tests)
  use this path. The migration of individual callsites is step 6.
- Add `def _sweep_idle(self) -> None` implementing ADR D4 "Idle sweep"
  **exactly**. Precondition: caller holds `_lock`. Postcondition:
  caller still holds `_lock` on return. Implementation: scan
  `_projects` for slots with `ref_count == 0 AND (now - last_access) >= _idle_ttl_seconds`; release `_lock` before
  calling `_close_evicted(root, reason="idle")` for each victim;
  re-acquire `_lock` before return. The release-reacquire dance is
  the load-bearing detail (see ADR D4 "Idle sweep" — the `_lock` is
  `threading.Lock`, NOT reentrant, so `_close_evicted` → `close_project`
  → `with self._lock` would deadlock without the release). A comment
  above the dance must cite ADR D4 "Idle sweep" by name.
- Add `def _admit_with_lru(self, root: Path) -> ProjectSlot`
  implementing ADR D4 "LRU admission" exactly: if
  `_max_projects <= 0` or `len(_projects) < _max_projects`, create
  normally; otherwise collect `(last_access, root)` tuples for slots
  with `ref_count == 0`, sort, pop the smallest, call
  `_close_evicted(victim, reason="lru")`, then create the new slot.
  If no evictable candidates, raise `RegistryFullError(self._max_projects)`.
- Add `def _close_evicted(self, root: Path, reason: str) -> None`: a
  thin wrapper over `close_project(root)` that logs at `INFO` with
  `reason` in the message.
- Modify `close_all()` (`service.py:297-321`) to implement ADR D6
  "graceful drain": set `_shutting_down=True` first, then loop until
  `time.monotonic() > deadline` (5-second bounded drain) checking
  for busy slots, sleeping 0.1s between checks; after the drain,
  force-close any remaining slots (logging a `WARNING` for each
  still-busy slot). The 5.0 second constant is an inline literal with
  a comment citing ADR D6. It is intentionally NOT configurable.
- Add `def busy_roots(self) -> list[Path]` — returns list of resolved
  roots with `ref_count > 0` under `_lock`. Used by step 6's MCP error
  shape and by step 10's tests.
- Add `def snapshot(self) -> list[dict]` — returns one dict per slot
  with `root`, `last_access`, `ref_count`, `idle_seconds`
  (derived from `time.monotonic() - last_access`). Used by the
  `list_projects` MCP tool in step 7.
- Keep the existing `close_project(root)` as the single teardown
  path. Do NOT inline its body — `_close_evicted` delegates to it.

**Tests added.**

- `src/vaultspec_rag/tests/test_service_registry.py` (may exist; if
  not, create). Add a dedicated `class TestLeaseApi:` with these
  eight integration-marked tests (each decorated with
  `@pytest.mark.integration`, each using the session-scoped
  `embedding_model` fixture and a real `VaultStore(root)` against
  `tmp_path`). These tests are NOT pure unit tests — they are
  integration tests in disguise (no Qdrant subprocess — uses Qdrant
  local/embedded mode via real `VaultStore(root)` against `tmp_path`,
  real GPU, real embedded Qdrant):
  - `test_lease_increments_refcount`
  - `test_lease_decrements_on_exit`
  - `test_sweep_evicts_idle`
  - `test_lru_admission_evicts_oldest`
  - `test_lru_full_raises`
  - `test_close_all_drains_then_force`
  - `test_acquire_blocks_during_shutdown`
  - `test_peek_does_not_change_refcount`
- Every test constructs a real `ServiceRegistry`, real
  `EmbeddingModel` (via the existing session-scoped fixture
  `embedding_model`), real temp vault roots with a single markdown
  file each, and real `VaultStore` via `_create_slot`. No mocks —
  no Qdrant subprocess — uses Qdrant local/embedded mode via real
  `VaultStore(root)` against `tmp_path`.
- `test_sweep_evicts_idle` manipulates `slot.last_access` by assigning
  a past monotonic time directly (the dataclass is non-frozen). This
  is NOT a mock — it is a legitimate test seam into a public mutable
  field.
- `test_close_all_drains_then_force` spawns a thread that holds a
  lease for longer than the 5-second deadline, asserts `close_all()`
  returns in bounded time, and asserts the busy slot was force-closed
  with a warning log entry.

**Definition of done.**

- `ruff check src/vaultspec_rag/service.py src/vaultspec_rag/tests/test_service_registry.py` is clean.
- `uv run pytest src/vaultspec_rag/tests/test_service_registry.py -m integration -x`
  is green with the eight new integration-marked tests.
- No existing test under `src/vaultspec_rag/tests/` regresses (run
  the full unit suite). The existing references to `get_project` in
  production code still work because step 6 migrates them next; for
  now, `get_project` is a compatibility alias for `peek_project` so
  the tree stays green between steps 4 and 6.
- `_sweep_idle`'s release-reacquire dance is covered by
  `test_sweep_evicts_idle` via a real multi-slot scenario.

**Dependencies.** Steps 1 (config knobs) and 2 (GraphCache relocation
makes `service.py`'s imports cleaner). Step 4 explicitly adds a
temporary `get_project = peek_project` alias so step 6 can migrate
callsites in a separate commit without breaking the tree.

### Step 5 — Collapse `api.py._engine` onto `ServiceRegistry.lease`

**Goal.** Delete the parallel `_Engine` / `_engine` / `get_engine` /
`reset_engine` cache in `api.py` and rewire every facade function
(`index`, `index_codebase`, `search_vault`, `search_codebase`,
`list_documents`, `get_related`) to route through
`ServiceRegistry.lease(root)` per ADR D5.

**Files touched.**

- `src/vaultspec_rag/registry.py` (NEW — module-level singleton holder)
- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/mcp_server.py` (replace module-level
  `_registry = ServiceRegistry()` with `_registry = get_registry()`)
- `src/vaultspec_rag/__init__.py` (verify — see N1 below)
- `src/vaultspec_rag/tests/test_adr_regression.py` (lines 114 and
  183 currently import `_engine_lock`; must be updated — see below)
- any test fixture that called `reset_engine()` (migrate to
  `_registry.close_all()`)

**Changes.**

- **Precondition (not optional cleanup):** Create
  `src/vaultspec_rag/registry.py` containing the module-level
  `_REGISTRY: ServiceRegistry` singleton, `get_registry() -> ServiceRegistry` accessor, and `reset_registry()` for tests. Both
  `mcp_server.py` and `api.py` import `get_registry` from
  `registry.py`. This breaks the otherwise-fatal cycle (`api.py`
  would import `mcp_server.py` to get `_registry`, but
  `mcp_server.py` already imports from `service.py` which would
  then chain back through `api.py`). `mcp_server.py`'s existing
  module-level `_registry = ServiceRegistry()` line must be
  replaced by `_registry = get_registry()` in THIS SAME STEP.
- Update `tests/test_adr_regression.py` lines 114 and 183: remove
  `_engine_lock` import; rewrite the assertions to test
  ServiceRegistry's lock semantics instead (either delete the
  obsolete `_engine_lock` sanity assertions or rewrite them to
  assert the new ServiceRegistry-based path — whichever is more
  faithful to each test's original intent).
- Before deleting `GraphCache` re-export: run `grep -rn "from vaultspec_rag.api import GraphCache" "from .api import GraphCache"` across `src/` and the tests dir. If
  there are ZERO consumers after step 2, the re-export can be
  deleted; if there are any remaining consumers, keep the shim and
  open a follow-up task. The plan explicitly flags this as a
  pre-condition check, not a hidden assumption.
- Delete `_Engine` class (`api.py:40-80`), `_engine` global
  (`api.py:83`), `_engine_lock` (`api.py:84`), `get_engine`
  (`api.py:87-119`), and `reset_engine` (`api.py:122-134`).
- Rewrite every facade function to import the module-level
  `_registry` via `from .registry import get_registry` (the new
  module created above). Each facade function becomes a ~3-line
  body: `with _registry.lease(root_dir) as slot: return slot.searcher.search_vault(query, top_k=top_k)` and similar. The
  lease's `__exit__` handles refcount decrement automatically.
- `index()` and `index_codebase()` must also invalidate the slot's
  `graph_cache` after a full or incremental reindex, matching the
  existing behavior at `api.py:154` and preserving the "code changes
  don't affect vault relationships" rule at `api.py:181`.
- Update `__all__` in `api.py` to drop `get_engine` and
  `reset_engine`. No `__init__.py` change required (verified:
  `__init__.py:46-69` does not currently export `get_engine` or
  `reset_engine`); only verify the file does not need editing.
  `GraphCache` handling: per the grep result above.
- Migrate any tests that called `reset_engine()` (if any remain) to
  `_registry.close_all()`.

**Tests added.** None net-new. This step is a pure refactor; coverage
comes from the existing facade-function tests plus step 10's
integration tests.

**Definition of done.**

- `grep -rn "_Engine\|get_engine\|reset_engine\|_engine_lock" src/vaultspec_rag/` returns ZERO matches (the shim is entirely
  deleted, not stubbed).
- `grep -rn "from vaultspec_rag.api import GraphCache" src/` matches
  the pre-step pre-condition check outcome (zero or documented).
- `ruff check src/vaultspec_rag/api.py src/vaultspec_rag/__init__.py`
  is clean.
- The existing `test_api.py` (if present) or the facade tests in
  `test_adr_regression.py` pass unchanged.
- `uv run vaultspec-rag test src/vaultspec_rag/tests/` is green.

**Dependencies.** Steps 2 and 4. Step 2 must have landed first so that
`GraphCache` is not entangled with `_Engine` when `_Engine` is
deleted. Step 4 must have landed first so the lease API actually
exists.

### Step 6 — Migrate MCP tool handlers to `lease()` and wrap `RegistryFullError`

**Goal.** Convert every MCP tool handler callsite in
`src/vaultspec_rag/mcp_server.py` from `_registry.get_project(root)`
to `with _registry.lease(root) as slot` and wrap each handler body in
a `try/except RegistryFullError` that returns a structured error dict
per ADR D4 "Error propagation".

**Files touched.**

- `src/vaultspec_rag/mcp_server.py`

**Changes.**

- Grep confirmation before editing: the current callsites at lines
  212, 552, 606, 651, 744, 791, 840 each do
  `slot = _registry.get_project(root)` followed by a body that uses
  `slot.searcher`, `slot.store`, `slot.vault_indexer`, or
  `slot.code_indexer`.
- Line 212 (`_ensure_watcher`): convert to
  `slot = _registry.peek_project(root)`. Watcher wiring is
  non-request-path and MUST NOT bump `ref_count` per ADR D3.
- Lines 552, 606, 651, 744, 791, 840: wrap each handler body in
  `try: with _registry.lease(root) as slot: ...` and add a bare
  `except RegistryFullError as e: return {"ok": False, "error": "registry_full", "message": str(e), "max_projects": _registry.max_projects, "busy_projects": [str(p) for p in _registry.busy_roots()]}`.
- The `_ensure_watcher(root)` call (lines 564, 625, 762, 808) stays
  INSIDE the `with` block so the watcher install happens while a
  lease is held — but `_ensure_watcher` itself uses `peek_project`,
  so it does not double-increment the refcount.
- Preserve all existing `_shutting_down` guards and the
  `anyio.to_thread.run_sync` wiring.
- Critical verification: after editing, `grep -n "_registry\.get_project" src/vaultspec_rag/mcp_server.py` must return ZERO matches. The
  `get_project = peek_project` alias added in step 4 is removed at
  the END of step 6 (last change of the commit) so the migration is
  verified complete.
- Verify that `_ensure_watcher` at line 193 uses `peek_project` (it
  was migrated in step 4's alias but step 6's final grep confirms no
  `get_project` callsites remain).

**Tests added.**

- `src/vaultspec_rag/tests/test_mcp_server.py`: add a
  `TestRegistryFullError` class with two tests:
  `test_search_vault_returns_registry_full_error` (constructs a
  registry at `max_projects=1`, leases one slot in a thread, then
  calls the MCP tool for a second root and asserts the returned dict
  matches the ADR D4 error shape) and
  `test_peek_project_path_used_by_ensure_watcher` (asserts that
  calling `_ensure_watcher(root)` does NOT bump `ref_count` on the
  registry).
- No mocks: both tests use real subprocess-free in-process registry +
  real VaultStore + real embedding model (session fixture).

**Definition of done.**

- `grep -n "_registry\.get_project" src/vaultspec_rag/mcp_server.py`
  returns zero matches.
- `grep -n "get_project" src/vaultspec_rag/service.py` matches only
  the permanent `peek_project` definition (the temporary alias added
  in step 4 is deleted).
- Every MCP tool handler body is wrapped in `try/except RegistryFullError`.
- `ruff check src/vaultspec_rag/mcp_server.py src/vaultspec_rag/service.py` is clean.
- Unit tests from step 4 and step 6 both green.

**Dependencies.** Steps 4 and 5. Step 4 provides the lease API; step
5 ensures `api.py` no longer holds a parallel cache that could
absorb some of the traffic.

### Step 7 — `list_projects` and `evict_project` MCP tools

**Goal.** Add the two admin MCP tools from ADR D7 so that operators
can observe and surgically evict project slots.

**Files touched.**

- `src/vaultspec_rag/mcp_server.py`

**Changes.**

- Add `async def list_projects(project_root: str | None = None)`
  decorated with `@mcp.tool()` (following the pattern at
  `mcp_server.py:552` et al.). Body: `data = await anyio.to_thread.run_sync(_registry.snapshot)`; format each
  slot dict into the ADR D7 response shape
  (`root`, `last_access_iso` via
  `datetime.fromtimestamp(time.time() - idle_seconds, tz=UTC).isoformat()`
  or similar derivation from monotonic `idle_seconds`, `idle_seconds`,
  `ref_count`); return `{"projects": [...], "max_projects": _registry.max_projects, "idle_ttl_seconds": _registry._idle_ttl_seconds}`. The `project_root` parameter is
  accepted and ignored for signature parity with other admin tools
  (ADR D7 "parity with other tools").
- Add `async def evict_project(root: str) -> dict`. Body: resolve
  `Path(root).resolve()`; acquire `_registry._lock` in a worker
  thread; if root not in `_projects`, return
  `{"evicted": False, "reason": "not_found"}`; if
  `slot.ref_count > 0`, return `{"evicted": False, "reason": "busy"}`;
  otherwise release the lock and call `_registry.close_project(root)`
  (reusing the watcher-stop-first path) and return
  `{"evicted": True, "reason": "forced"}`.
- Both tools use `anyio.to_thread.run_sync` per the project-wide MCP
  tool convention.
- The `reason="idle"` value is reserved for internal logging — never
  returned by `evict_project` per ADR D7.

**Tests added.**

- `src/vaultspec_rag/tests/test_mcp_server.py`: in `TestAdminTools`
  (new class), add `test_list_projects_returns_snapshot`,
  `test_list_projects_empty_registry`,
  `test_evict_project_busy_returns_busy`,
  `test_evict_project_unknown_returns_not_found`,
  `test_evict_project_success_returns_forced`. All use a real
  in-process registry and seed one or two real project slots via the
  session `embedding_model` fixture. No mocks.
- `test_list_projects_empty_registry` is NOT allowed to assert only
  that `projects == []`. It must additionally read
  `get_config().service_max_projects` and
  `get_config().service_idle_ttl_seconds` separately and assert that
  `result['max_projects']` and `result['idle_ttl_seconds']` match
  those configured defaults — not assume the numeric constants.

**Definition of done.**

- `ruff check src/vaultspec_rag/mcp_server.py` is clean.
- Five new tests green.
- The response shapes exactly match ADR D7 (reviewer-visible
  assertion: no extra keys, no missing keys).

**Dependencies.** Step 6 (lease API + error propagation wiring must
be in place so the admin tools speak the same error vocabulary).

### Step 8 — CLI `service projects list|evict` subcommands

**Goal.** Expose the two new MCP tools through the existing Typer
CLI at `vaultspec-rag service projects {list,evict}` per ADR D7.

**Files touched.**

- `src/vaultspec_rag/cli.py`

**Changes.**

- Declare `service_projects_app = typer.Typer(help="Inspect and evict project slots on a running RAG service.")` near the
  `service_app = typer.Typer(...)` declaration at `cli.py:92`, and
  register it: `service_app.add_typer(service_projects_app, name="projects")`.
- Add helper `_try_mcp_admin(tool_name: str, args: dict, port: int | None) -> dict | None` modeled after the existing `_try_mcp_search`
  at `cli.py:619` and `_try_mcp_reindex` at `cli.py:557`. It MUST be
  a brand-new helper, NOT a generalization (per ADR D7 — keeping
  the existing fast-path helpers stable). Behavior per ADR D7:
  returns `None` only for "service unreachable" (connection refused),
  returns the raw dict otherwise so the caller can distinguish "tool
  error" from "service down".
- Add `@service_projects_app.command("list")` with `--port` option
  (default `None`, CLI fast-path resolution via
  `_resolve_service_port` or equivalent helper used by existing
  service commands). Calls `_try_mcp_admin("list_projects", {}, port)`. Renders a Rich table with columns `Root` (truncated to 60
  chars from the right with `…`), `Idle` (humanized: `2m 14s`,
  `1h 5m`), `Refs`, `Last access` (HH:MM:SS local time). Footer:
  `{n}/{max} slots, idle TTL {ttl}s`.
- Add `@service_projects_app.command("evict")` taking a positional
  `root: str` argument and `--port` option. Calls
  `_try_mcp_admin("evict_project", {"root": root}, port)`. Exit
  codes per ADR D7: `0` for `evicted=True` (reason in
  `{"idle","forced"}`), `1` for busy, `2` for not_found, `3` for
  service unreachable (helper returned `None`). Exit-code
  propagation via `raise typer.Exit(n)`.

**Tests added.** Tests are split into two files — pure in-process
CLI tests (no live service) and real-subprocess integration tests:

- `src/vaultspec_rag/tests/test_cli.py` — in-process, no live
  service. Four tests using Typer's `CliRunner`:
  - `test_projects_list_help_renders`
  - `test_projects_evict_help_renders`
  - `test_projects_list_service_down_returns_exit_3`
  - `test_projects_evict_service_down_returns_exit_3`
    The two `*_service_down_*` tests exercise the case where
    `_try_mcp_admin` returns `None` (service unreachable), triggered
    by pointing the CLI at an unused port via `--port` or
    `VAULTSPEC_RAG_PORT`. NO mocks — the unreachability is real
    because no service is running.
- `src/vaultspec_rag/tests/integration/test_service_projects_cli.py`
  (NEW FILE) — real subprocess. Four tests that start a real
  service via `_helpers._service_env`, run `vaultspec-rag service projects list/evict ...` via `subprocess.run`, and assert exit
  codes plus stdout content:
  - `test_projects_list_against_running_service`
  - `test_projects_evict_busy_returns_exit_1`
  - `test_projects_evict_idle_returns_exit_0`
  - `test_projects_evict_unknown_returns_exit_2`
    Both `@pytest.mark.integration` and
    `@pytest.mark.subprocess_gpu` apply to each.

**Definition of done.**

- `vaultspec-rag service projects list --help` renders the help text
  without error.
- `vaultspec-rag service projects evict --help` renders the help
  text.
- `ruff check src/vaultspec_rag/cli.py` is clean.
- Four in-process `test_cli.py` tests green (unit-suite run).
- Four real-subprocess integration tests in
  `integration/test_service_projects_cli.py` green under `-m "integration and subprocess_gpu"`.

**Dependencies.** Step 7 (MCP tools must exist before the CLI can
call them).

### Step 9 — Wire `install_daemon_log_rotation` into `mcp_server.main()`

**Goal.** Install the rotating file handler inside the child process
immediately after `configure_logging()` and before `uvicorn.run()`
per ADR D1 "Install ordering (CRITICAL)".

**Files touched.**

- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/logging_config.py` (no new code — just a
  potential export addition if needed)

**Changes.**

- Add `from .logging_config import configure_logging, install_daemon_log_rotation` to `mcp_server.py` imports.
- Inside `main()`, immediately after argparse and BEFORE
  constructing or running uvicorn, call `configure_logging()`.
  Reviewer-verified: `mcp_server.main()` currently does NOT call
  `configure_logging()` at all — it is called by the CLI layer at
  `cli.py:243`, which is the parent process, not the daemon. This
  is a behavior change — the daemon previously inherited the
  parent's `configure_logging()` state via the inherited stderr fd;
  with rotation it must call its own to install the rotating
  handler on its OWN root logger after the inherited handler list
  (which is empty in the spawned interpreter) is cleared.
- Then, if `cfg.service_log_max_bytes > 0`, call
  `install_daemon_log_rotation(log_path, max_bytes=cfg.service_log_max_bytes, backup_count=cfg.service_log_backup_count)`.
- Then call `uvicorn.run(...)` as today.
- The exact install order per ADR D1 is: argparse →
  `configure_logging()` → `install_daemon_log_rotation()` →
  `uvicorn.run()`. A one-line comment above the install call must
  cite ADR D1 "Install ordering (CRITICAL)" by name.
- The helper receives the resolved log path from `_log_file()`-style
  resolution (see `cli.py:1025`). If `mcp_server.main` does not
  currently have a log-path resolver, add `_resolve_log_file()` in
  `mcp_server.py` that composes `cfg.status_dir / cfg.log_file`
  identically to `cli._log_file()`. Do NOT cross-import from
  `cli.py` — the resolver is small enough to duplicate.
- The stdio-mode branch (`mcp_server.py:932-942`) does NOT install
  the handler. stdio mode is for one-shot CLI tooling, not long-lived
  daemon use. Add a comment explaining the asymmetry.
- If `cfg.service_log_max_bytes == 0`, the helper still installs the
  handler but configures it with `maxBytes=0`, which is the standard
  `RotatingFileHandler` "never roll" semantics (ADR D8).
- Critical: there are NO unit tests for this wiring. A unit test
  would have to mock either `configure_logging`, `uvicorn.run`, or
  the install helper itself, which violates the project-wide
  no-mocks mandate. Coverage for step 9 comes entirely from step
  10's `test_log_rotation_creates_backups` and
  `test_log_rotation_post_rollover_writes_to_active` integration
  tests.

**Tests added.** None. See "Critical" note above. This is a
deliberate design choice per the no-mocks mandate.

**Definition of done.**

- `grep -n "install_daemon_log_rotation" src/vaultspec_rag/mcp_server.py`
  shows exactly one call inside the HTTP-mode branch.
- `grep -n "configure_logging()" src/vaultspec_rag/mcp_server.py`
  returns at least one match inside `main()`.
- The call sits between `configure_logging()` and `uvicorn.run()`.
  Line-order verification via `grep -n`.
- `ruff check src/vaultspec_rag/mcp_server.py` is clean.
- The stdio-mode branch is untouched.

**Dependencies.** Step 3 (handler + helper must exist). Step 10 (the
tests covering this wiring come next — step 9's correctness is
demonstrated by step 10 passing).

### Step 10 — Integration tests (real subprocess + GPU + Qdrant)

**Goal.** Add six end-to-end integration tests under a new file
`src/vaultspec_rag/tests/integration/test_service_eviction.py` that
exercise the complete ADR D9 matrix plus the `close_all`
drain-busy-slots guarantee from ADR D6.

**Files touched.**

- `src/vaultspec_rag/tests/integration/_helpers.py` (NEW — shared
  helpers module; underscore prefix keeps pytest from collecting it
  as a test file)
- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
  (update: imports helpers from `_helpers` instead of defining them)
- `src/vaultspec_rag/tests/integration/test_service_eviction.py` (new
  file; eviction is conceptually distinct from lifecycle so a
  new file is preferable to growing
  `test_service_lifecycle.py` past ~600 lines)

**Changes.**

- **Sub-step 10.0 — Extract integration helpers (FIRST sub-task of
  Step 10, a precondition for all other Step 10 work):** Move
  `_service_env`, `_get_ephemeral_port`, `_poll_health`,
  `_wait_for_exit` from
  `tests/integration/test_service_lifecycle.py` to a new module
  `tests/integration/_helpers.py` (underscore prefix keeps pytest
  from collecting it as a test file). Both `test_service_lifecycle.py`
  and the new `test_service_eviction.py` import from `_helpers`.
  Definition of done for 10.0: existing lifecycle tests still pass
  after the move; the new eviction tests import from `_helpers`
  not from sibling test modules.
- New file `test_service_eviction.py` imports the helpers from
  `_helpers` (NOT from the sibling `test_service_lifecycle.py`).
- Add six functions, each decorated with BOTH
  `@pytest.mark.integration` AND `@pytest.mark.subprocess_gpu` (the
  two markers stack: integration is broad, subprocess_gpu is the
  granular runtime requirement). The EXACT names from the ADR D9
  matrix plus the `close_all_drains_busy_slots` addition from the
  supervisor:
  - `test_idle_ttl_evicts_quiescent_slots` (ADR D9 item 1) —
    markers: `integration`, `subprocess_gpu`.
  - `test_lru_cap_evicts_oldest` (ADR D9 item 2) — markers:
    `integration`, `subprocess_gpu`.
  - `test_evict_busy_returns_busy` (ADR D9 item 3) — markers:
    `integration`, `subprocess_gpu`, `robustness`. Run
    `N = 20` evict_project calls in a tight loop while a parallel
    thread fires `search_vault` at the same project. Assert
    "at least one of 20 returned `reason='busy'`". Document in the
    test docstring: "This test is timing-sensitive on fast
    hardware. The robustness marker indicates it may be re-run on
    flake; CI must run it at least once but flakes do not block
    merge." If on a future RTX 5090-class card the busy window
    closes entirely, the test will need a slower mechanism —
    out-of-scope for #45.
  - `test_log_rotation_creates_backups` (ADR D9 item 4) — markers:
    `integration`, `subprocess_gpu`. With `max_bytes=4096`,
    `backup_count=2`, driving DEBUG-level search output past
    several rotation thresholds, polling the filesystem for
    rotated files with a 2-second deadline.
  - `test_log_rotation_post_rollover_writes_to_active` (ADR D9
    item 5) — markers: `integration`, `subprocess_gpu`. Fully
    specified sequence:
    1. Start service via
       `_helpers._service_env(env_overrides={"VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES": "4096", "VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT": "3", "VAULTSPEC_RAG_LOG_LEVEL": "DEBUG"})`.
    1. Drive log emissions by calling `search_vault` via the MCP
       HTTP client in a loop until
       `Path(log_path + '.1').exists()` (poll every 100ms, deadline
       10s).
    1. Record
       `log_active_size_at_rollover = Path(log_path).stat().st_size`.
    1. Issue 5 more `search_vault` calls.
    1. Sleep 500ms to let the daemon flush.
    1. Assert
       `Path(log_path).stat().st_size > log_active_size_at_rollover`
       (active file grew).
    1. Read `Path(log_path).read_bytes()` and
       `Path(log_path + '.1').read_bytes()` and assert at least one
       DEBUG-level identifier from the post-rollover phase appears
       in the active file but NOT in `.1`. Identifier strategy:
       include the test's `t0_iso = datetime.now().isoformat()`
       captured AFTER step 3 in any subsequent search query string,
       so the daemon's request log echoes it.
  - `test_close_all_drains_busy_slots` (ADR D6) — markers:
    `integration`, `subprocess_gpu`. Start the service. Issue 8
    concurrent `search_vault` calls from a thread pool to keep
    multiple slots busy with overlapping latency (use 8 different
    temporary project_root paths so each lease pins a different
    slot). Immediately after fire-and-forget, call
    `vaultspec-rag service stop` (the parent CLI command). Measure
    shutdown wall time. Assert: shutdown completed in under 7
    seconds (5s drain + 2s grace). Read `service.log`
    post-shutdown. Assert: at least one `Force-closing busy slot`
    WARNING is present (because 8 concurrent searches against
    fresh project roots each take >1s of cold-load + index time,
    exceeding the 5s drain). If the warning is absent on a
    particular run (slots happened to drain in time), the test
    still passes provided shutdown was clean — but assert the
    registry was cleanly torn down by checking `service.json` was
    removed.
- Every test sets up a fresh temp `status_dir` via `_service_env`
  and passes env overrides for
  `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS`,
  `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`,
  `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`,
  `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT`, and
  `VAULTSPEC_RAG_LOG_LEVEL` as needed.
- `test_log_rotation_creates_backups` MUST flush the handler after
  each batch (per ADR D9 flake note) via an MCP tool call that
  triggers `handler.flush()` — or, lacking a tool, by sending
  enough records that CPython's `RotatingFileHandler.shouldRollover`
  naturally fires. Poll the filesystem for rotated files with a
  2-second deadline rather than asserting immediately.
- **No mocks. No patches. No monkeypatch. No skip marks.** If a
  test is flaky on Windows, the fix is real retries with bounded
  deadlines, never `pytest.skip()`.

**Definition of done.**

- All six tests present with the exact names above.
- `uv run vaultspec-rag test src/vaultspec_rag/tests/integration/test_service_eviction.py -m subprocess_gpu -v` passes end-to-end on the local RTX 4080.
- `grep -n "pytest\.skip\|monkeypatch\|MagicMock\|@patch" src/vaultspec_rag/tests/integration/test_service_eviction.py`
  returns zero matches.
- Each test's assertions are specific to the ADR behavior (not
  tautological).

**Dependencies.** Steps 1–9. This is the end-to-end verification
step; every earlier change has to be in place for these tests to
pass.

### Step 11 — Lint, type, docs, changelog

**Goal.** Bring the modified surface back to a known-clean state and
update user-facing docs for the new knobs and CLI commands.

**Files touched.**

- All files modified in earlier steps (for final pre-commit pass)
- `README.md` (CLI reference section for `service projects`)
- `CHANGELOG.md` (new `## Unreleased` entries for the beta gate fix)
- `docs/` if applicable — the `.vaultspec` rule at
  `.claude/rules/vaultspec-rag.builtin.md` lists the current CLI
  surface; updating it is optional and at the executor's
  discretion.

**Changes.**

- Run `pre-commit run --all-files` as the canonical gate. This
  covers ruff (check + format), `ty check src/vaultspec_rag` (the
  project's type checker), `taplo` (TOML linter),
  `mdformat-check` (the README change), and any other configured
  hooks. Every violation must be fixed in-place — NO `# noqa` and
  NO `# type: ignore` escape hatches.
- mypy is NOT configured in this project (verified: no
  `[tool.mypy]` section in `pyproject.toml`, no mypy in any
  dependency group). Do NOT run mypy.
- Add a `## Service project eviction and log rotation` subsection to
  `README.md` near the existing `server service` docs, covering the
  four new config keys (with defaults), the `service projects list`
  and `service projects evict` commands, and a one-paragraph
  explanation of the idle TTL + LRU semantics.
- Add one `CHANGELOG.md` entry under `## Unreleased` summarizing
  issue #45 and linking to the ADR wiki link (the ADR stem only —
  no absolute paths in changelog).
- Do NOT touch `vaultspec-core` or any cross-repo shared rule file.

**Tests added.** None.

**Definition of done.**

- `pre-commit run --all-files` exits clean (zero violations).
- `README.md` diff includes the new subsection.
- `CHANGELOG.md` diff includes the new Unreleased entry.

**Dependencies.** Steps 1–10 (everything).

### Step 12 — Final verification

**Goal.** Run the full test suite and a manual smoke walkthrough
before opening the PR.

**Files touched.** None.

**Changes.** None.

**Verification.**

- Full unit suite: `uv run vaultspec-rag test src/vaultspec_rag/tests/ -x -v`. Must be green.
- Full integration suite: `uv run vaultspec-rag test src/vaultspec_rag/tests/integration/ -m subprocess_gpu -v`. Must
  be green (all pre-existing lifecycle tests AND the six new
  eviction tests).
- Manual smoke walkthrough:
  - `uv run vaultspec-rag server service start` (starts the daemon
    on the default port).
  - `uv run vaultspec-rag search "service eviction"` — hits project
    A, populates one slot.
  - `cd <other-project> && uv run vaultspec-rag search "ADR"` —
    hits project B, populates second slot.
  - `uv run vaultspec-rag service projects list` — should render a
    Rich table with two rows, non-zero idle seconds, ref_count=0,
    footer `2/16 slots, idle TTL 1800s`.
  - `uv run vaultspec-rag service projects evict <project-A>` —
    should print a success message and exit 0.
  - `uv run vaultspec-rag service projects list` — should show one
    row (project B only).
  - Inspect `~/.vaultspec-rag/service.log` — should exist and be
    non-empty. Bump `VAULTSPEC_RAG_LOG_LEVEL=DEBUG` and drive enough
    searches to trigger one rollover, then inspect
    `service.log.1` for the rotated content.
  - `uv run vaultspec-rag server service stop` — should exit
    cleanly within the 5-second drain window.
- If any step of the walkthrough fails, the PR is not ready. Fix
  and re-run.

**Definition of done.**

- Produce a phase summary at
  `.vault/exec/2026-04-12-store-eviction-log-rotation/2026-04-12-store-eviction-log-rotation-phase1-summary.md`
  with `tags: ['#exec', '#store-eviction-log-rotation']`
  documenting: each step's completion status, any deviations from
  the plan with rationale, the manual smoke walkthrough output,
  and the final test counts (unit + integration).

**Dependencies.** Steps 1–11.

## Parallelization

Steps 1–3 are largely independent of each other and each other's
modifications to `config.py`, `graph_cache.py`/`api.py`, and
`logging_config.py`. They could in theory run on parallel branches
and merge, but because this plan mandates one commit per step in
sequence (see "Commit cadence"), parallelization is left to future
work with independent ADRs.

Steps 4–6 form a strict linear chain (lease API → api.py collapse →
MCP migration) and must run serially.

Steps 7–9 each depend on step 6 and can theoretically parallelize,
but step 9 should land last of the three because it is the
"everything wired up" step and makes step 10's integration tests
executable.

Step 10 depends on steps 1–9. Steps 11 and 12 are sequential tails.

## Risks & mitigations

The top five implementation risks and their concrete mitigations:

**Risk 1 — Deadlock in `_sweep_idle` release-reacquire dance.** The
ADR D4 "Idle sweep" specifies releasing `_lock` before calling
`_close_evicted` (which itself takes `_lock` via `close_project`)
because `_lock` is a `threading.Lock`, not an `RLock`. A subtle bug
in the release-reacquire pattern could leave `_lock` unlocked when
an exception propagates up from `_close_evicted`, causing the next
caller to hang.
*Mitigation.* Step 4 implements the release-reacquire inside a
`try/finally` so `_lock` is always re-acquired before return.
Step 4's `test_sweep_evicts_idle` asserts that a second lease after
a sweep completes without hang. Step 10's
`test_close_all_drains_busy_slots` adds a real-subprocess concurrent
stressor.

**Risk 2 — Windows FD re-`dup2` regression.** If a future refactor
replaces `DaemonRotatingFileHandler` with a plain `RotatingFileHandler`,
fds 1 and 2 will silently "stick" on the first rotated file and the
backup count accounting goes wrong with no error message.
*Mitigation.* Step 10's `test_log_rotation_post_rollover_writes_to_active`
is the direct regression guard. Without the re-dup2, the test fails
deterministically on Windows. Step 3 also has a fd-aware unit test
(`test_daemon_rotating_handler_doRollover_re_dups_stdio`) that uses
real `os.dup`/`os.dup2` fd save-and-restore so the doRollover path
is covered without integration overhead.

**Risk 3 — `RegistryFullError` blocking operators who hit a valid
workload.** ADR D8 ships with `service_max_projects=16`. An operator
running 17+ workspaces simultaneously will see a structured error
dict on the 17th and must retry after a slot frees. This is
user-visible and surprising on first encounter.
*Mitigation.* Step 7's `list_projects` and the Rich-table CLI in
step 8 let operators see which slots are busy and evict a specific
one manually. The structured error in step 6 includes
`busy_projects` so the error message is actionable. README update
in step 11 documents the knob prominently so operators know the
cap exists.

**Risk 4 — Silent double-cache if step 5 is skipped or partial.** If
any `api.py` facade function is missed during the step 5 rewrite, it
will keep routing through the (now-deleted) `_engine` and crash with
`NameError: _engine`, or worse, if the deletion is not followed
through (e.g., `_engine` left as a commented-out block), the crash
becomes a silent correctness bug where two caches hold the same
store.
*Mitigation.* Step 5's definition of done includes a `grep -rn` check
that returns zero matches for `_Engine|get_engine|reset_engine|_engine_lock`.
Step 5 is a full deletion, not a stub replacement. Step 6's tests
exercise every MCP tool handler path against a registry that is the
only cache in play.

**Risk 5 — Integration test flakiness on Windows.** Step 10's
log-rotation tests depend on CPython's `RotatingFileHandler`
flushing behavior, which can lag on Windows due to filesystem
buffering. A flaky test is worse than no test because it trains
operators to hit rerun.
*Mitigation.* Step 10 polls the filesystem for up to 2 seconds for
rotated files to appear, flushes the handler explicitly (or uses
`os.fsync`), and uses a very small `max_bytes` (4096) so rollover
triggers deterministically on a handful of records. The
`test_evict_busy_returns_busy` test asserts "at least one of N"
rather than a single timing-sensitive call. No `pytest.skip` is
ever added — if a test is flaky, the fix is bounded retries with
monotonic deadlines.

## Commit cadence

One commit per step. Twelve commits total. Suggested conventional
commit subject lines:

- Step 1: `feat(config): add service eviction and log rotation knobs`
- Step 2: `refactor: relocate GraphCache to its own module`
- Step 3: `feat(logging): add DaemonRotatingFileHandler with dup2 re-binding`
- Step 4: `feat(service): lease API with refcount, idle sweep, and LRU admission`
- Step 5: `refactor(api): collapse _engine cache onto ServiceRegistry.lease`
- Step 6: `refactor(mcp): migrate tool handlers to lease() + RegistryFullError`
- Step 7: `feat(mcp): add list_projects and evict_project admin tools`
- Step 8: `feat(cli): add service projects list and evict subcommands`
- Step 9: `feat(service): install daemon log rotation in mcp_server.main`
- Step 10: `test(integration): end-to-end eviction and log rotation coverage`
- Step 11: `chore: lint, type, README and CHANGELOG for #45`
- Step 12: `chore: final verification (no code changes)` — or, if no
  changes resulted, skip the commit and note the verification in the
  PR description instead.

Each commit MUST pass pre-commit hooks before `git commit` is
invoked. No `--no-verify`, no hook skips.

## Verification

Mission success for this phase is:

- All four ADR D8 config knobs present and env-override-wired in
  `src/vaultspec_rag/config.py`.
- `ServiceRegistry` exposes a context-manager `lease` API; every
  MCP tool handler callsite uses it; `peek_project` is reserved for
  non-request wiring (watcher install, lifespan preload).
- `RegistryFullError` is raised exactly when admission would exceed
  `service_max_projects` with no evictable candidates, and is
  surfaced as a structured `{"ok": False, "error": "registry_full", ...}` MCP response.
- `close_all` performs a bounded 5-second drain before force-closing
  busy slots, per ADR D6.
- `api.py._engine`, `_engine_lock`, `_Engine`, `get_engine`,
  `reset_engine` no longer exist anywhere in `src/vaultspec_rag/`.
- `GraphCache` lives in `src/vaultspec_rag/graph_cache.py`; the
  `api.py` re-export shim is either deleted (if zero remaining
  consumers) or documented with a follow-up task.
- `DaemonRotatingFileHandler` exists in `logging_config.py` and is
  installed by `mcp_server.main()` between `configure_logging()` and
  `uvicorn.run()` per ADR D1 "Install ordering (CRITICAL)".
- `list_projects` and `evict_project` MCP tools exist and return the
  exact response shapes from ADR D7.
- `vaultspec-rag service projects list|evict` CLI commands exist
  with exit codes `0/1/2/3` per ADR D7.
- All eight unit tests from step 4 pass against the real registry.
- All six integration tests from step 10 pass against real
  subprocess + real GPU + real Qdrant.
- `pre-commit run --all-files` is clean on every modified file
  (ruff, `ty`, taplo, mdformat-check, and all configured hooks).
  No `# noqa` or `# type: ignore` escape hatches.
- The manual smoke walkthrough in step 12 produces the expected
  output at every stage.

Honest limitation: step 9's wiring (`install_daemon_log_rotation` into
`mcp_server.main`) has no unit-test coverage on purpose — a unit test
would require mocking either `configure_logging`, `uvicorn.run`, or
the install helper itself, which violates the project-wide no-mocks
mandate. The two integration tests
`test_log_rotation_creates_backups` and
`test_log_rotation_post_rollover_writes_to_active` are the only
coverage. This is a deliberate trade-off and is called out here so
reviewers do not flag it as missing test coverage.
