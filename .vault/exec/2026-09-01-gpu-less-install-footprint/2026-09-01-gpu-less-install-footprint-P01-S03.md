---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:84771a3b81dbe8465fa1994799a66874f0e5318dd88b8465e7f0a84f225eda59'
step_id: 'S03'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# Prove built package metadata and Linux resolution exclude the CUDA stack from the base install

## Scope

- `tools packaging guard tests`

## Changes

- `M` `src/vaultspec_rag/tests/test_packaging_metadata.py`
- verify: `uv run --no-sync pytest src/vaultspec_rag/tests/test_packaging_metadata.py -q` -> pass
