---
tags:
  - '#exec'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
body_hash: 'sha256:b96288aebf09f65f7b9936b522defbe2660a3c5175b0fe3023e2c22a2e6ecb41'
step_id: 'S02'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---

# Thread the group selector through install-run and the torch flow down to the ensure-direct-dep call without breaking the idempotent re-run path

## Scope

- `src/vaultspec_rag/commands/_torch_flow.py`

## Description

- Threaded `torch_group: str | None` from the CLI through `install_run`, `_run_torch_config_install`, `_handle_canonical_state`, and `_ensure_torch_direct_dep` into `ensure_direct_torch_dep`.

## Outcome

The selector reaches the write helper without breaking the idempotent re-run path.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (143 passed).
