---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: '2026-04-12'
modified: '2026-07-27'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

## Description

### Goal

Extend `VaultSpecConfigWrapper` with the four ADR D8 knobs
(`service_idle_ttl_seconds`, `service_max_projects`,
`service_log_max_bytes`, `service_log_backup_count`) wired through
`EnvVar` and `_ENV_OVERRIDE_MAP`.

### Files touched

- `src/vaultspec_rag/config.py`
- `src/vaultspec_rag/tests/test_config.py` (new)

### What was done

- Added four new `EnvVar` members with the `VAULTSPEC_RAG_SERVICE_*`
  env var names.
- Added the four keys to `_ENV_OVERRIDE_MAP`.
- Added the four keys to `_RAG_DEFAULTS` with int types so the
  env-override coercion in `__getattr__` dispatches correctly.
- Created `test_config.py` with eight tests: four default-value
  assertions and four env-override tests that manipulate
  `os.environ` inside try/finally (no monkeypatch).

## Outcome

### Test results

- `uv run pytest src/vaultspec_rag/tests/test_config.py -x -q` -
  8 passed.
- Pre-commit run on the two files passed all hooks (ruff, format,
  ty).

### Commit hash

`b11954e feat(config): add service eviction and log rotation config keys`

## Notes

### Deviations

None.

### Time spent

~10 minutes.
