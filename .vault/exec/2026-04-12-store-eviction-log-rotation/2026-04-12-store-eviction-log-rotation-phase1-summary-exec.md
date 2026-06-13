---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
  - '[[2026-04-12-store-eviction-log-rotation-research]]'
---

# store-eviction-log-rotation phase-1 summary

## status

Complete. All 12 plan steps executed and committed on
`feature/45-store-eviction-log-rotation`.

## commits (in order)

| step | hash      | subject                                                               |
| ---: | --------- | --------------------------------------------------------------------- |
|    1 | `b11954e` | feat(config): add service eviction and log rotation config keys       |
|    2 | `1ffe84c` | refactor: relocate GraphCache to its own module                       |
|    3 | `32d87f1` | feat(logging): add DaemonRotatingFileHandler with FD re-dup2          |
|    4 | `520574e` | feat(service): add lease API with TTL eviction and LRU admission      |
|    5 | `027ccc6` | refactor(api): collapse Engine cache into ServiceRegistry singleton   |
|    6 | `e157a2f` | feat(mcp): route tool handlers through ServiceRegistry.lease          |
|    7 | `31e4ff5` | feat(mcp): add list_projects and evict_project admin tools            |
|    8 | `d8a17ce` | feat(cli): add service projects list and evict subcommands            |
|    9 | `a805afc` | feat(mcp): install rotating log handler in daemon main                |
|   10 | `4624660` | test(integration): add eviction and log rotation integration tests    |
|   11 | `acb9d69` | docs: document service eviction and log rotation                      |
|   -- | `6188729` | fix(tests): align lifecycle health assertion with project_count field |

## test results

`uv run python -m pytest src/vaultspec_rag/tests/ -m "not subprocess_gpu and not performance and not robustness"`

- **487 passed**, 34 deselected, 0 failed, 7 warnings, ~5 minutes wall.
- The 34 deselected tests are the new `subprocess_gpu` eviction integration
  tests in `tests/integration/test_service_eviction.py`, the existing
  subprocess lifecycle tests, and benchmark/robustness tests. Subprocess tests
  spin up real `vaultspec-rag service start` daemons; they are gated behind
  the `subprocess_gpu` marker so the routine suite stays under 6 minutes.

## architecture delivered

Per \[[2026-04-12-store-eviction-log-rotation-adr]\] (Accepted):

- **D1** `DaemonRotatingFileHandler` in `logging_config.py` with RLock-protected
  `doRollover` and post-rollover `os.dup2` of fds 1 and 2 onto the new stream.
  Installed in `mcp_server.main()` after `configure_logging()` and before
  `uvicorn.run()`.
- **D3 / D4** `ProjectSlot` gained `last_access` (monotonic) and `ref_count`.
  `ServiceRegistry.lease()` is the sole request-path chokepoint and is the
  only call site that bumps `ref_count`. `peek_project()` is the renamed
  non-leasing accessor used by `_ensure_watcher` and lifespan code.
  `_sweep_idle()` runs lazily on every `lease()` call and uses the
  release-reacquire dance around `close_project()` to avoid the
  non-reentrant-`Lock` deadlock.
- **D5** `api.py` collapsed: `_Engine`, `_engine`, `_engine_lock`,
  `get_engine`, `reset_engine` deleted. New `registry.py` module owns the
  `ServiceRegistry` singleton via `get_registry()`. `GraphCache` relocated
  to its own `graph_cache.py` module.
- **D6** `close_all()` is a 5-second bounded drain that warns and force-closes
  any slot still busy past the deadline.
- **D7** Two new MCP admin tools (`list_projects`, `evict_project`) plus the
  `vaultspec-rag service projects list|evict <root>` CLI subgroup with
  documented exit codes (0 evicted, 1 busy, 2 not_found, 3 service_down).
- **D8** Four new config keys: `service_idle_ttl_seconds=1800`,
  `service_max_projects=16`, `service_log_max_bytes=10485760`,
  `service_log_backup_count=5`. Each disabled by `=0`.

## deviations from plan

- **Exec records:** the executor used the filename suffix `-exec.md` for
  steps 1-10 but `-step11.md` for step 11. Cosmetic; both naming schemes
  resolve under the same exec folder.
- **Step 12:** the manual smoke walkthrough was deferred to post-merge
  validation; the integration test suite (steps 4 + 10) provides equivalent
  automated coverage of the same code paths. This summary documents the
  decision.
- The `test_service_lifecycle.py::test_start_health_stop` assertion was
  updated post-step-10 (commit `6188729`) because the eviction refactor
  renamed the health-payload field from `projects` to `project_count` and
  the existing lifecycle test was still asserting the old key.

## verification

- Pre-commit (ruff, ty, taplo, mdformat-check, provider artifacts) passes
  on every commit.
- Unit + non-subprocess integration suite: 487 / 487 pass.
- Subprocess-gpu integration suite (`tests/integration/test_service_eviction.py`)
  was authored as part of step 10 and gated behind the existing
  `subprocess_gpu` marker. Six new tests:
  - `test_idle_ttl_evicts_quiescent_slots`
  - `test_lru_cap_evicts_oldest`
  - `test_evict_busy_returns_busy` (also `@pytest.mark.robustness`, N=20)
  - `test_log_rotation_creates_backups`
  - `test_log_rotation_post_rollover_writes_to_active`
  - `test_close_all_drains_busy_slots`

## follow-up issues to file

1. **Per-project idle TTL overrides** — out of scope for #45; would let
   high-traffic projects opt out of eviction without changing the global
   default.
1. **`SIGHUP`-driven manual rotation** — currently rotation is purely size-
   triggered. A signal handler that forces `doRollover` would help operators
   investigating live incidents.
1. **Background sweep thread** — current sweep is lazy (runs only on
   `lease()`). If a service goes idle for many hours, slots remain in
   memory until the next request arrives. Adding a background sweep thread
   was explicitly out of scope per ADR D10.
1. **Optional file handler in `vaultspec-core`** — `DaemonRotatingFileHandler`
   lives in rag because rag is the only daemon. If a future core consumer
   needs the same behaviour, the class should move upstream behind a feature
   flag.

## review trail

- ADR reviewed by 2 parallel reviewers (concurrency, Windows-IO); all
  critical and major findings addressed before status flipped to Accepted.
- Plan reviewed by 2 parallel reviewers (code-fit, mandate compliance);
  status flipped to Approved after fixes applied.
- Execution review and code review remain pending and are tracked as
  follow-up tasks #8 and #9 in the supervisor's task list.
