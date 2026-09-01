---
tags:
  - '#research'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:db85739b1146dc751d2f00a3d07fb505c5c5c202b80b95dcd58166f73d7315c4'
related:
  - "[[2026-08-28-platform-backend-selection-research]]"
---
# `gpu-less-install-footprint` research: `separate package installation from CUDA inference provisioning`

A GPU-less Linux host currently receives the full CUDA stack during a normal package install even though local inference is intentionally unavailable there. The evidence supports a thin base distribution plus explicit CUDA provisioning, not CPU inference and not a CUDA extra whose resolver cannot select the required index.

## Findings

### Published base metadata, not the workspace lock, pulls CUDA on Linux

A cross-platform dry run of published `vaultspec-rag==0.4.21` for `x86_64-unknown-linux-gnu` resolves `torch==2.13.0`, triton, CUDA bindings, and fifteen `nvidia-*` packages. `pyproject.toml:20-23` makes torch and sentence-transformers base requirements. The cu130 source mapping at `pyproject.toml:138-146` is an uv workspace setting, not published wheel metadata; it cannot change a PyPI consumer's resolution. The existing platform research establishes the upstream Linux-wheel asymmetry.

### Moving torch alone does not create a light base

`sentence-transformers>=5.0` independently requires torch, as captured in `uv.lock:2111-2125`. A base install is therefore still heavy unless torch and its compute dependants move as one boundary. The explicit transformers floor must be assessed with that boundary so the published metadata does not reintroduce an inference dependency indirectly.

### The runtime is already safe without an installed inference stack

`src/vaultspec_rag/_gpu.py:36-100` imports torch only on a compute path, reports missing torch with remediation, and refuses a CPU-only build or absent CUDA device. `src/vaultspec_rag/embeddings.py:419-438` checks model dependencies only when compute is requested. Existing fresh-process coverage in `src/vaultspec_rag/tests/test_cli_index.py:883-889` proves control-plane fallback paths leave torch, sentence-transformers, transformers, qdrant-client, and onnxruntime unloaded.

### Existing provisioning is the correct CUDA boundary

`src/vaultspec_rag/commands/_torch_flow.py:140-320` configures a consumer project to use the pinned cu130 torch build and can synchronize it. `src/vaultspec_rag/cli/_gpu_errors.py:220-240` supplies tool-environment remediation. This is the correct place to select a CUDA build because ordinary published extras cannot convey uv's workspace-only source mapping. https://docs.astral.sh/uv/concepts/projects/dependencies/ and https://docs.astral.sh/uv/guides/integration/pytorch/ document that distinction.

### Alternatives differ in correctness, not just size

Keeping compute dependencies in the base leaves the reported Linux CUDA pull unchanged. A CPU-default plus CUDA extra creates a successful install whose default runtime is deliberately refused, and its extra cannot reliably select the required CUDA index for published users. Direct CPU and CUDA wheel matrices could express every supported ABI and platform but introduce a release-maintenance matrix while still not providing permitted CPU inference. A thin base with explicit GPU provisioning makes package installation small and keeps the existing GPU-only contract loud.

### Scope and unknowns

This work does not add CPU or MPS inference. The measured post-change on-disk size must be documented from a fresh Linux resolution during implementation; the issue's approximately five-gigabyte observation remains the baseline, not a claimed result for the revised package.

## Sources

- `pyproject.toml:20-23,138-146`
- `uv.lock:2111-2125`
- `src/vaultspec_rag/_gpu.py:36-100`
- `src/vaultspec_rag/embeddings.py:419-438`
- `src/vaultspec_rag/commands/_torch_flow.py:140-320`
- `src/vaultspec_rag/cli/_gpu_errors.py:220-240`
- `src/vaultspec_rag/tests/test_cli_index.py:883-889`
- `2026-08-28-platform-backend-selection-research`
- https://docs.astral.sh/uv/concepts/projects/dependencies/
- https://docs.astral.sh/uv/guides/integration/pytorch/
