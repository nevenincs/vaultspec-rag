---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S10'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Add --no-preprocess and --preprocess-trust-all to server start and the index/reindex verbs, forward the mode into the daemon env like --local-only, and print the untrusted-config notice with the remediation verb at server start

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/_process.py`
- `src/vaultspec_rag/cli/_index.py`

## Description

- Extend the daemon-env builder `_service_child_env` and the spawner `_spawn_service` in `src/vaultspec_rag/cli/_process.py` with a `preprocess_mode` parameter (`"off" | "trust_all" | None`), following the existing `--local-only` forwarding pattern: `off` writes `VAULTSPEC_RAG_PREPROCESS=off` and drops any inherited `TRUST_ALL`; `trust_all` writes `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1` and drops any inherited `PREPROCESS`; `None` leaves both untouched so an operator-set var survives. Clearing the opposing var makes the forwarded flag authoritative over inherited env.
- Add `--no-preprocess` and `--preprocess-trust-all` to `server start` in `src/vaultspec_rag/cli/_service_lifecycle.py`, resolved through `_resolve_preprocess_forward`: the two are mutually exclusive (passing both is a hard start failure with error `preprocess_flags_conflict`), and the resolved value is forwarded into the daemon spawn.
- Add the operator-visibility notice `_print_preprocess_start_notice`: when the resolved target root (`--target`, else cwd) has a preprocess config, print whether its rules will run under the effective mode (off/trust_all/trusted) or, when untrusted in the default mode, name the remediation verb `vaultspec-rag preprocess trust <root>`. Human-only so the `--json` envelope stays one document; best-effort (a missing or invalid config yields no notice); imports are function-local to keep the service-control surface torch-free.
- Promote `Path` to a runtime import in `_service_lifecycle.py` (was TYPE_CHECKING-only) and add `ctx: typer.Context` to `service_start` so the global `--target` resolves for the notice.
- Add the same two flags to the `index` verb in `src/vaultspec_rag/cli/_index.py` with matching mutual-exclusion (same `preprocess_flags_conflict` error string). For the in-process path, `_apply_preprocess_env` sets the tri-state env before indexing begins (the `preprocess_mode` property reads it live, so no config rebuild is needed). The flags shape an in-process run only: when a service will handle the index (an explicit or auto-detected `--port`), `_warn_preprocess_flag_ignored_when_delegating` warns loudly (logger plus a human `Warning:` line, so `--json` stdout stays one envelope) that the flag does not apply to a delegated run and the run proceeds under the daemon's start-time mode - a loud warning rather than silent acceptance. The flag help text says the running service uses the mode it was started with.

## Outcome

- `server start` and `index` gain the two mutually-exclusive flags; `server start` forwards the mode into the daemon env exactly like `--local-only` and `index` applies it in-process; the untrusted-config notice prints at start.
- `ruff check` clean; `basedpyright` reports 0 errors across `src/vaultspec_rag/cli`.
- Verified via S11: the flag-conflict error, the `_service_child_env` forwarding matrix (off/trust_all/None), the `index` conflict error and delegating-warning (loud warning, run proceeds), and `_apply_preprocess_env` selecting the resolved mode all assert directly with no live daemon. Adjacent index paths stay green (`test_cli.py`/`test_indexer_unit.py`, 161 tests).

## Notes

- Scope resolution: the Step row names "the index/reindex verbs" (ADR D7). There is no separate `reindex` verb; the `index` verb delegates to the service or runs in-process. The orchestrator confirmed `cli/_index.py` is in scope (the "indexer files" exclusion was anti-collision with the parallel executor owning `src/vaultspec_rag/indexer/`, not `cli/_index.py`).
- The service-delegation path deliberately does NOT honour the flag - the daemon preprocesses under its own start-time mode - so the CLI warns loudly (per the orchestrator's direction) rather than silently accepting a flag it cannot apply, and the delegated run still proceeds. The effective mode for the start notice is the forwarded flag when present, else `get_config().preprocess_mode` (the same env the daemon inherits), so the notice reflects what the daemon will actually do.
