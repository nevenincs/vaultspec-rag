---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:945e0428fc3db56ea240037821dd2277076530f83eb375cab03b7e1163795fd4'
step_id: 'S05'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# Update no-GPU binary acquisition coverage for the thin published base

## Scope

- `.github/workflows/acquisition.yml`

## Changes

- `M` `.github/workflows/acquisition.yml`
- verify: `uv run --no-sync actionlint .github/workflows/acquisition.yml` -> pass
