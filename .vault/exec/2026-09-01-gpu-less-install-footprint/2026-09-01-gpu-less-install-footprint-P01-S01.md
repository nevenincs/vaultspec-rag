---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:b015b50987ebb8862cf10cb53748a9d249c81386f61c36dcb673826f4d5e191d'
step_id: 'S01'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---
# Move local inference dependencies behind the explicit compute boundary

## Scope

- `pyproject.toml and uv.lock`

## Changes

- `M` `pyproject.toml`
- `M` `uv.lock`
- verify: `uv lock; uv sync --group dev` -> pass
