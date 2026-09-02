---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:21fd6eff15f9ff194d2a87156068d3ca08d82038d8d17badc4c5ba578d9d6162'
step_id: 'S06'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# Request the GPU runtime for MCP and standalone binary compute launchers

## Scope

- `MCP builtin and PyApp packaging configuration`

## Changes

- `M` `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`
- `M` `tools/binaries/build_pyapp.py`
- `M` `tools/binaries/tests/test_build_pyapp.py`
- `M` `tests/smoke_check.py`
- `M` `src/vaultspec_rag/tests/test_install_mode.py`
- verify: `uv run --no-sync pytest tools/binaries/tests/test_build_pyapp.py src/vaultspec_rag/tests/test_install_mode.py -q` -> pass
