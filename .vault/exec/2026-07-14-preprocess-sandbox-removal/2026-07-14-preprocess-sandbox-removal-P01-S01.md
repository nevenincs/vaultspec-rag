---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S01'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Rewrite the sandbox module to a direct-launch helper: keep curated_child_env and default_popen_handle, delete resolve_hook_sandbox, \_probe_backend, stage_source, SandboxUnavailableError, and the HookSandbox protocol

## Scope

- `src/vaultspec_rag/indexer/_hook_sandbox.py`

## Description

- Gut the sandbox module to a direct-launch helper: keep `curated_child_env` (allow-list env stripping) and `default_popen_handle` (piped `Popen` with curated env and scratch cwd).
- Delete `HookSandbox`, `SandboxHandle`, `SandboxUnavailableError`, `resolve_hook_sandbox`, `_probe_backend`, and `stage_source`.
- Rewrite the module docstring to the trust-based framing.

## Outcome

`src/vaultspec_rag/indexer/_hook_sandbox.py` exports exactly `curated_child_env` and `default_popen_handle`; stdlib-only, torch-free.

## Notes

None.
