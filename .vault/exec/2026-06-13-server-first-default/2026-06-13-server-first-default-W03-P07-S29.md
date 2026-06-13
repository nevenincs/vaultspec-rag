---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S29'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# report the qdrant binary resolution source and supervised-server liveness by reading the qdrant runtime state

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Report the qdrant binary resolution source by reading the runtime resolver (operator env / managed provisioned dir / on PATH / absent) without executing the binary.
- Report supervised-server liveness by reading the qdrant runtime state snapshot in-process; never spawn a server to test it.
- Make the dimension backend-aware: in local-only mode the on-disk store needs no binary so it reads `ready` regardless; in server mode an absent binary is `not_ready` with an install/`--local-only` remediation, a supervised child that is not live is `not_ready`, and a resolvable binary (with no child supervised in this read-only process) is `ready`.
- Carry the resolution source, resolved path, effective server mode, and the full runtime state dict as structured `info`.

## Outcome

- The qdrant dimension reports the real resolution source (`provisioned` on the dev host) and reads the runtime snapshot read-only. The local-only path reports `ready` with `server_mode=false`, and an operator-supplied env binary is reported as the `env` source.

## Notes

- Implemented in `src/vaultspec_rag/_readiness.py` (`_qdrant_readiness`), not directly in `api.py`; see S26 notes. The verify-before-execute contract is untouched: resolution is read-only and the supervisor is never started.
