---
tags:
  - '#reference'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:c70bcf0d438154b7e6bf1c4dd3aa049fc94077c4885bcd2d48af6a40bc6b71fd'
related:
  - "[[2026-08-28-platform-backend-selection-research]]"
---

# `platform-backend-selection` reference: `published dependency boundary and CUDA provisioning`

## Summary

The published base distribution currently cannot be lightweight on Linux: `pyproject.toml:20-23` declares both `torch>=2.4` and `sentence-transformers>=5.0`; the latter independently requires torch. A Linux cross-platform dry run for release `0.4.21` resolves torch, triton, CUDA bindings, and fifteen `nvidia-*` distributions. The workspace-only cu130 source mapping at `pyproject.toml:138-146` does not appear in wheel metadata, so moving or retaining that mapping cannot alter an installer of the PyPI wheel.

`src/vaultspec_rag/_gpu.py:36-100` is the central, function-local compute gate. It already gives a clear missing-torch remediation and rejects CPU-only torch or a missing CUDA device. `src/vaultspec_rag/commands/_torch_flow.py:140-320` is the existing provisioning seam: it configures a consumer project to resolve the pinned cu130 torch build and can synchronize that environment. `src/vaultspec_rag/cli/_gpu_errors.py:220-240` provides the equivalent tool-environment remediation.

A thin base must therefore move torch and every dependency that independently reaches torch, including sentence-transformers, out of published base metadata. The compute path remains opt-in and is provisioned only for CUDA-capable workspaces; control-plane commands remain usable without it. Do not label this as CPU inference: `src/vaultspec_rag/_gpu.py:58-100` must retain its refusal of CPU compute.

The implementation needs a built-wheel metadata and Linux dry-run guard, not only a TOML assertion. It must fail if base requirements regain torch, sentence-transformers, or an NVIDIA package, while existing GPU provisioning tests continue to prove the cu130 path. Documentation must say that `--local-only` selects Qdrant storage only; `docs/backends.md:74-82` shows it never selects a Python dependency set.
