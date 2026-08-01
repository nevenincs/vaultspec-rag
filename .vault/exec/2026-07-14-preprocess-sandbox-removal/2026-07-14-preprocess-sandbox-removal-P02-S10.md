---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:3f9760f47bb5471264c2de3b4e3ca0844b03fbf6df41db1c3ec3d4eb74d49fcb'
step_id: 'S10'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Remove the --preprocess-unsandboxed flag and env forwarding from server start, keeping --no-preprocess

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Remove `--preprocess-unsandboxed` and `_resolve_preprocess_forward` from `server start`; `preprocess_forward` is now derived inline from `--no-preprocess`.
- Update the start notice: rules run directly with the service's privileges.

## Outcome

`server start --no-preprocess` unchanged; unsandboxed flag gone.

## Notes

None.
