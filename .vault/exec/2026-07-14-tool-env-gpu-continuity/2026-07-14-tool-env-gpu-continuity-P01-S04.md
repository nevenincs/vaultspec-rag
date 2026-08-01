---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:44a6b841110fd425346ea1356a1eb4ffeb58d76f1988b9eccd14f1834dd4c274'
step_id: 'S04'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add a prominent uvx-ephemeral warning to server start, as human text plus a warnings field inside the json success envelope (never stray text), naming the installed-tool path and the stop-the-service-before-forced-reinstall guidance

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Add `_ephemeral_env_warning(interpreter)` returning warning lines only for uvx-ephemeral interpreters.
- `service_start` prints the warning in human mode before the CUDA pre-flight; `_await_service_ready` gains an `env_warnings` parameter and folds them into the `started` --json envelope as a `data.warnings` list, keeping the single-envelope broker contract.

## Outcome

Committed as e6bfb3e (same file as S03). Covered by TestEphemeralEnvWarning.

## Notes

The warning is emitted on the start path only; the already_running early-return path never resolves a daemon interpreter, so it stays warning-free by construction.
