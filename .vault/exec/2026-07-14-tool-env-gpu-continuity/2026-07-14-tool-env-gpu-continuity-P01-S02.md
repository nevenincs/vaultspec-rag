---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Rewrite the CPU-only messaging in warn_if_active_torch_not_gpu to emit the immediate escape hatch plus the durable receipt fix selected by env classification, sourcing both strings from the new helper

## Scope

- `src/vaultspec_rag/cli/_gpu_errors.py`

## Description

- Rewrite the CPU-only branch of `warn_if_active_torch_not_gpu` to select remediation by `classify_runtime_env`: uv-tool envs get the immediate escape hatch plus the durable receipt-carrying reinstall; uvx-ephemeral envs get the not-the-installed-tool explanation plus the reinstall-with-service-stopped guidance; project venvs keep the install-and-sync path.
- Source both command strings from the S01 helpers (no scattered literals).

## Outcome

Committed as 8a857ad (same-file change with S01). Verified by TestEphemeralEnvWarning and TestRemediationCommands.

## Notes

S01 and S02 share one commit because both rewrote `src/vaultspec_rag/cli/_gpu_errors.py` in one pass; the step records keep the 1:1 traceability.
