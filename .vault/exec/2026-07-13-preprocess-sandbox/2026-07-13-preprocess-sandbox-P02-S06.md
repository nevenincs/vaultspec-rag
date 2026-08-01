---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
body_hash: 'sha256:e5f948683b897a1572307e4bfdd739192cc77d9c462bef2d51ba0ab4a7a8f689'
step_id: 'S06'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Create the HookSandbox abstraction: backend protocol, staged-input plus curated-env plus scratch-cwd contract, capability probe, and the fail-closed server-mode policy

## Scope

- `src/vaultspec_rag/indexer/_hook_sandbox.py`

## Description

- Create the `HookSandbox` / `SandboxHandle` protocols so the runner drains a
  contained child exactly as it drained a bare subprocess.
- Implement the shared mandatory hardening every backend layers on: staging the
  source into a per-run scratch dir (`stage_source`), the secret-free
  `curated_child_env` (drops all tokens and `VAULTSPEC_RAG_*`, keeps only the
  loader-required allow-list), and scratch cwd.
- Implement `resolve_hook_sandbox` with the fail-closed policy: server mode with
  no backend raises `SandboxUnavailableError`; the unsandboxed opt-in returns
  None loudly; local mode with no backend returns None with a warning.
- Add `cached_backend` so the probe runs once per spawn worker, not per file.
- Keep the module stdlib-only so the spawn-worker import chain stays torch-free.

## Outcome

The abstraction is the single authority the runner consults; every server hook
launch flows through it. Ruff and basedpyright clean.

## Notes

The allow-list had to grow beyond the obvious PATH/SystemRoot: AppContainer
initialization resolves USERPROFILE/LOCALAPPDATA/APPDATA/TEMP/TMP during
startup, and a missing one fails CreateProcessW with ERROR_ENVVAR_NOT_FOUND
(203). These are path strings, not credentials, and the sandbox still denies the
child read of what they point at, so forwarding them leaks nothing exploitable.
