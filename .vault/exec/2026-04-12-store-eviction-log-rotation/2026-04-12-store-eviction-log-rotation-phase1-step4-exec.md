---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-06-30'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-4

## goal

Grow `ServiceRegistry` into the ADR D3/D4/D6 shape: refcounted lease
context manager, `peek_project` alias, LRU admission with
`RegistryFullError`, idle sweep with release-reacquire dance, and
bounded `close_all` drain.

## files touched

- `src/vaultspec_rag/service.py`
- `src/vaultspec_rag/tests/test_service_registry.py`

## what was done

- `ProjectSlot`: added `last_access: float` and `ref_count: int`
  default-0 fields.
- Added module-level `RegistryFullError` with `max_projects` attribute.
- `ServiceRegistry.__init__` now reads
  `cfg.service_idle_ttl_seconds` and `cfg.service_max_projects`;
  exposed `max_projects` and `idle_ttl_seconds` properties.
- Renamed `get_project` to `peek_project` (with a temporary class-level
  `get_project = peek_project` alias for step 6 migration).
- Added `lease` context manager delegating to `_acquire` / `_release`.
- Added `_acquire` (fast-path + LRU-admit + sweep under `_lock`),
  `_release`, `_sweep_idle` (with the documented release-reacquire
  dance), `_admit_with_lru` (sorts zero-ref candidates by
  `last_access`, raises `RegistryFullError` when everyone is busy),
  `_close_evicted` (thin wrapper over `close_project` with a reason
  log line), `busy_roots`, and `snapshot`.
- `close_all` rewritten to set `_shutting_down` first, poll every 0.1s
  for a 5.0s bounded drain, then stop watchers + force-close busy
  slots with WARNING logs. The 5.0s constant is hardcoded per
  ADR D6.
- Added `TestLeaseApi` class with eight integration-marked tests
  using the session-scoped `embedding_model` fixture and real
  `VaultStore`/`tmp_path` vaults (no mocks).

## deviations from plan

- The plan's `test_close_all_drains_then_force` description spawns a
  worker thread holding a `lease` past the deadline. That shape
  fails: after `close_all()` clears `_projects`, the worker's eventual
  `_release` hits a `KeyError` because lease release looks up the
  slot via `with reg._lock: slot.ref_count -= 1` (slot object is
  still live via the local variable, so this is OK) — but the plan's
  original snippet mutated `reg._projects[root].ref_count` by dict
  lookup *inside* the worker. Rewrote the test to pin `ref_count`
  directly on the slot and measure drain elapsed time (`4.5 < elapsed < 7.0` bounds the 5s deadline from both sides). This still exercises
  the drain+force-close code path and verifies `_projects` is
  cleared afterward.

## test results

- `pytest src/vaultspec_rag/tests/test_service_registry.py::TestLeaseApi -m integration -v` -> 8 passed.
- `pytest src/vaultspec_rag/tests/test_service_registry.py -m integration` -> 36 passed.
- `ruff check` + `ty check src/vaultspec_rag` clean.

## commit hash

`520574e feat(service): add lease API with TTL eviction and LRU admission`

## time spent

~45 minutes (largest code step; one test revision).
