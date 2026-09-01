---
tags:
  - '#research'
  - '#platform-backend-selection'
date: '2026-08-28'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:8a27156def1c27bb391a9d30c5c32699be001e3634ef24af5f5874d720d268d9'
related:
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
  - '[[2026-09-01-platform-backend-selection-reference]]'
---
# `platform-backend-selection` research: `which accelerator each platform can actually use, and what the install puts there`

`2026-03-06-gpu-rag-stack-adr` records a user mandate: GPU-only inference, no CPU fallback. The code enforces it through one gate, and the gate tests for CUDA. Two consequences follow in opposite directions: Apple silicon has a working GPU the gate cannot see, and a GPU-less Linux host is handed five gigabytes of CUDA it can never use.

Neither is a case for weakening the mandate. The evidence favors resolving an explicitly supported accelerator at runtime, refusing CPU, and moving platform-specific CUDA provisioning behind the existing install verb. Direct fleet measurement now closes the original MPS evidence gap: the complete production dense, sparse, and reranker stack runs concurrently on an 8 GiB Apple silicon host with CPU fallback disabled. The ADR must settle MPS admission policy and the Linux migration path.

## Findings

### The gate is CUDA-shaped, not accelerator-shaped

`_gpu.py` is the single load-bearing gate: every local-mode compute path obtains torch through `load_torch()`, which admits or refuses the process. Its refusal message names CUDA specifically, and its check is `torch.cuda.is_available()`.

That single-gate design makes a second backend tractable. The CUDA assumption has nevertheless leaked past it: `torch.cuda.*` appears in `embeddings.py`, `api.py`, `search/_searcher.py`, `memory_probe.py`, `_readiness.py`, `server/_state.py`, and `cli/_gpu_errors.py`. The report at `api.py:813` is the visible symptom—on Apple silicon it reports no GPU and 0 VRAM, a false statement about unified-memory hardware.

Admission is the deepest coupling. It interrogates free VRAM on a discrete CUDA device. MPS instead exposes process allocator figures and a recommended working-set limit over unified memory, so it needs a backend-specific admission policy rather than renamed CUDA accessors.

### The macOS gap was accepted knowingly, but the original reason no longer holds

`2026-03-06-gpu-rag-stack-adr` lists inability to run on macOS without CUDA among its negative consequences. That was a recorded consequence, not a regression. The mandate's intent is nevertheless to use an accelerator and never silently use CPU; an MPS backend that is measured with fallback disabled satisfies that intent.

### The exact production model stack runs concurrently on MPS without CPU fallback

The fleet host `Gergelys-MacBook-Neo.local` ran macOS 26.5.1 build 25F80 on Apple ARM64 with 8 GiB unified memory. A bounded probe used Python 3.13.11, torch 2.13.0, sentence-transformers 5.7.0, transformers 5.16.1, and `PYTORCH_ENABLE_MPS_FALLBACK=0`. The exact production revisions for Qwen dense embedding, SPLADE sparse encoding, and the BGE reranker all loaded together on `mps:0` and completed forward passes with finite outputs.

With all three models resident, torch reported 3,720.1 MiB current MPS allocation and 4,218.5 MiB driver allocation against its 5,461.3 MiB recommended working-set limit. After all forwards the driver allocation was 4,228.7 MiB. This establishes functional support on the fleet's smallest-memory Mac; it does not establish throughput or thermal behavior.

The probe used one cleanup-trapped `/tmp` directory. Package downloads, a virtual environment, and transient gated model copies stayed within it; peak scratch was 4.0 GiB and cleanup was verified. Persistent uv and Hugging Face caches and the runner checkout were unchanged. The implementation surface and exact model revisions are recorded in `2026-09-01-platform-backend-selection-reference`.

### The CUDA weight on Linux comes from PyPI, not from this project

`pyproject.toml` pins torch to the cu130 index under `[tool.uv.sources]`, which is workspace-scoped and absent from published wheel metadata. An installing user therefore resolves torch from PyPI. In `torch@2.13.0`, Linux receives a 527 MB wheel plus gated NVIDIA and Triton dependencies, while Windows and macOS wheels carry no CUDA dependencies.

Linux is consequently the only platform where a plain install arrives CUDA-capable by accident, whether or not a GPU exists.

### Windows and macOS already depend on a provisioning step

Because their PyPI wheels carry no CUDA, a bare Windows install cannot satisfy the current gate. `cli/_gpu_errors.py` already detects that state and directs the user to `vaultspec-rag install`, which configures the cu130 index and installs the GPU build.

Provisioning CUDA through the install verb on Linux would reuse an existing mechanism and align all platforms. It changes when the GPU build arrives, not whether runtime accepts CPU, so the gate can continue refusing CPU exactly as it does now.

### Remaining unknowns are performance and migration, not MPS correctness

No sustained indexing benchmark, battery/thermal run, or long-lived service soak was performed on MPS. The probe establishes exact-model functional compatibility and concurrent residency only. The size of a GPU-less Linux install after packaging changes and the upgrade behavior of an already-provisioned CUDA environment also remain unmeasured.

## Sources

- `src/vaultspec_rag/_gpu.py`
- `src/vaultspec_rag/_gpu_admission.py`
- `src/vaultspec_rag/api.py:813`
- `src/vaultspec_rag/cli/_gpu_errors.py`
- `pyproject.toml`
- `2026-09-01-platform-backend-selection-reference`
- `torch@2.13.0` PyPI metadata and wheel listing
- https://docs.pytorch.org/docs/stable/notes/mps.html
- https://docs.pytorch.org/docs/stable/mps_environment_variables.html
- https://huggingface.co/naver/splade-v3
- https://huggingface.co/BAAI/bge-reranker-v2-m3
