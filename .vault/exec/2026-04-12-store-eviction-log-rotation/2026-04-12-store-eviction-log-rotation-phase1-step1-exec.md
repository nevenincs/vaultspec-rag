---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-1

## goal

Extend `VaultSpecConfigWrapper` with the four ADR D8 knobs
(`service_idle_ttl_seconds`, `service_max_projects`,
`service_log_max_bytes`, `service_log_backup_count`) wired through
`EnvVar` and `_ENV_OVERRIDE_MAP`.

## files touched

- `src/vaultspec_rag/config.py`
- `src/vaultspec_rag/tests/test_config.py` (new)

## what was done

- Added four new `EnvVar` members with the `VAULTSPEC_RAG_SERVICE_*`
  env var names.
- Added the four keys to `_ENV_OVERRIDE_MAP`.
- Added the four keys to `_RAG_DEFAULTS` with int types so the
  env-override coercion in `__getattr__` dispatches correctly.
- Created `test_config.py` with eight tests: four default-value
  assertions and four env-override tests that manipulate
  `os.environ` inside try/finally (no monkeypatch).

## test results

- `uv run pytest src/vaultspec_rag/tests/test_config.py -x -q` -
  8 passed.
- Pre-commit run on the two files passed all hooks (ruff, format,
  ty).

## deviations

None.

## commit hash

`b11954e feat(config): add service eviction and log rotation config keys`

## time spent

~10 minutes.
