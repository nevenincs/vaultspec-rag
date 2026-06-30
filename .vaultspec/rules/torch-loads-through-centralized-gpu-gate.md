---
name: torch-loads-through-centralized-gpu-gate
---

# Torch loads through one centralized GPU gate

## Rule

Every local-mode path that needs torch for compute must obtain it through the single
centralized loader `vaultspec_rag._gpu.load_torch()` - which imports torch, asserts a
CUDA device, and raises hard on a CPU-only build - never a naked `import torch`; service
call paths (the `mcp/` server, the `serviceclient/` client, and the CLI service-control
commands) must stay torch-import-free; and if the installer provisions torch at all it
must be the cu130 GPU build, never a CPU wheel accepted silently.

## Why

vaultspec-rag is GPU-only and never runs inference on CPU. The `2026-06-30` torch
hardening found the hard CUDA gate duplicated across four sites (embeddings, the service
reranker, the searcher reranker, and CLI warmup), each re-implementing
`if not torch.cuda.is_available(): raise` - three with a copy-pasted message - so the
"who, when, and how torch loads" was uncontrolled and a CPU-only build could only be
caught wherever someone remembered to check. The same work found the installer reporting
`PyTorch configuration: already configured` from pyproject text while the active
interpreter carried a CPU-only torch wheel (a bare `uv tool` / `pip install` resolves
torch from PyPI because the cu130 pin is workspace-scoped and absent from published wheel
metadata, and `--torch-backend` is `uv pip`-only). Centralizing the load and probing the
real wheel is what makes the GPU-only contract enforceable and legible rather than
silently violated.

## How

- **Good:** a compute site calls `torch = load_torch()` and uses the returned module;
  `load_torch()` raises `RuntimeError` (CPU-only or no GPU) or `ImportError` (absent) so
  the failure is hard and loud, with one canonical message.
- **Good:** read-only probes that must tolerate a CPU-only or torch-absent host (the
  `/health` and `/metrics` reporters, readiness diagnosis, the memory probe) keep their
  own guarded function-local import and report `cuda=False` rather than raise - they are
  the deliberate exception and do not call `load_torch()`.
- **Good:** the installer probes the active interpreter's wheel
  (`warn_if_active_torch_not_gpu`) and, when torch was meant to be provisioned, warns
  loudly on a CPU-only or absent wheel with topology-aware remediation; an explicit
  torch opt-out is respected silently.
- **Bad:** a naked module-scope `import torch`, or a fresh inline
  `if not torch.cuda.is_available(): raise` on a compute path instead of routing through
  `load_torch()`.
- **Bad:** importing torch (or `sentence_transformers`) anywhere reachable from a service
  call path, or reporting install success over a CPU-only torch wheel.

## Source

The `2026-06-30` torch import-discipline and install-provisioning audits and the
GPU-only mandate they served. Sibling rules `index-workers-stay-cpu-only` (torch imports
stay function-local so spawn workers never initialise CUDA) and
`gpu-consumer-single-thread`.
