---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:e12a93ed3a640bb72e4aafaca6f6a86b06bd776c133bf02529dc2a2740071ecc'
step_id: 'S11'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Update the preprocess status verb to report direct execution and the two-state mode instead of the resolved sandbox backend

## Scope

- `src/vaultspec_rag/cli/_preprocess.py`

## Description

- Drop the `sandbox_backend` field from `preprocess status` JSON and the `Sandbox:` human line; `_sandbox_backend` and its unwired placeholder deleted.
- `_status_effect_line` states rules execute with the operator's privileges; `run-one` loses the sandbox kwargs.

## Outcome

`preprocess status` reports mode, config presence, rule count, and `would_run` only.

## Notes

BREAKING for scripts reading `sandbox_backend` from the status JSON.
