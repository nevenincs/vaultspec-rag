---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:8ce0ab12c2c870f300d0fa13d70eff9851cd4dcbcab1cf8da6a0f43d70e26f4b'
step_id: 'S04'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# Document base, CUDA-provisioned, and local-only install costs and behavior

## Scope

- `README.md and docs installation guides`

## Changes

- `M` `README.md`
- `M` `docs/installation.md`
- `M` `docs/backends.md`
- `M` `docs/mcp.md`
- verify: `uv run --no-sync mdformat --check README.md docs/installation.md docs/backends.md docs/mcp.md` -> pass
