---
tags:
  - '#plan'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
tier: L2
related:
  - '[[2026-09-01-gpu-less-install-footprint-adr]]'
  - '[[2026-09-01-gpu-less-install-footprint-research]]'
  - '[[2026-09-01-platform-backend-selection-reference]]'
modified: '2026-09-01'
body_hash: 'sha256:e11df6f2c97cc8bbba5b1f9473d4561be41238ad6244cff7ce82d15ac8ad1d87'
---

# `gpu-less-install-footprint` plan

## Steps

### Phase `P01` - Separate published inference dependencies

Make the base distribution torch-free while preserving explicit CUDA provisioning and a runnable GPU development environment.

- [x] `P01.S01` - Move local inference dependencies behind the explicit compute boundary; `pyproject.toml and uv.lock`.
- [x] `P01.S02` - Preserve actionable missing-compute remediation at the lazy inference boundary; `src/vaultspec_rag/embeddings.py and tests`.
- [x] `P01.S03` - Prove built package metadata and Linux resolution exclude the CUDA stack from the base install; `tools packaging guard tests`.
- [x] `P01.S06` - Request the GPU runtime for MCP and standalone binary compute launchers; `MCP builtin and PyApp packaging configuration`.
- [x] `P01.S07` - Update tool and CLI remediation for the explicit GPU runtime; `GPU dependency diagnostics and tests`.

### Phase `P02` - Explain and validate the install paths

Describe the separate storage and GPU provisioning choices, then align release acquisition with the thin base.

- [x] `P02.S04` - Document base, CUDA-provisioned, and local-only install costs and behavior; `README.md and docs installation guides`.
- [x] `P02.S05` - Update no-GPU binary acquisition coverage for the thin published base; `.github/workflows/acquisition.yml`.
