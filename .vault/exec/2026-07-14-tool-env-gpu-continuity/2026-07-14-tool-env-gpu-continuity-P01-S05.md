---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S05'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add classifier truth-table tests (tools dir, archive-v0 cache, project venv, env-var overrides, Windows path shapes), refusal-message content tests, and a single-source test asserting the remediation strings derive from the cu130 constants

## Scope

- `src/vaultspec_rag/tests/test_service_env_preflight.py`

## Description

- Add TestRuntimeEnvClassifier (nine cases: Windows tool shape, archive-v0 shape, UV_TOOL_DIR/UV_CACHE_DIR overrides, project venv, other, interpreter walk-up for Scripts and bin, label totality).
- Add TestRemediationCommands (escape hatch targets interpreter + cu130 backend token; durable command carries CU130_INDEX_URL) - the single-source guard.
- Add TestEphemeralEnvWarning (fires for archive-v0 interpreter, silent for tool env).

## Outcome

Committed as 0ce8364. 19 passed in the file; basedpyright and ty clean.

## Notes

None.
