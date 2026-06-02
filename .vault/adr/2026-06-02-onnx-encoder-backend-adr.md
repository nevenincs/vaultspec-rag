---
tags:
  - '#adr'
  - '#onnx-encoder-backend'
date: '2026-06-02'
related:
  - "[[2026-06-02-onnx-encoder-backend-research]]"
---

# `onnx-encoder-backend` adr: `onnx-o4 dense encoder backend behind a flag with torch fallback` | (**status:** `accepted`)

## Problem Statement

The embed stage dominates indexing wall-clock (~17 min for 112k chunks at the optimal
`bs=32`). The documented next lever was an ONNX-O4 dense-encoder backend (sentence-transformers
cites ~1.83x on short text). This ADR decides whether and how to adopt it, grounded in the
research and in empirical feasibility spikes run on this machine.

## Considerations

Three findings, two of them measured here, shape the decision:

- **Environment (measured).** `onnxruntime-gpu` requires CUDA 12 (`cublasLt64_12.dll`); this
  project's torch is CUDA 13 (`2.12.0+cu130`, cuDNN 9.2). A bare onnxruntime-gpu install fails
  to create `CUDAExecutionProvider` and silently falls back to CPU (which would be a large
  regression, not a speedup). It loads on GPU only when the CUDA-12 runtime is bundled
  alongside via the `nvidia-*-cu12` packages plus `onnxruntime.preload_dlls()` — a fragile
  dual-CUDA coexistence next to the cu130 torch, with real risk to the working GPU torch.
- **Batch regime (research).** The ~1.83x is a GPU + short-text + batch\<=4 latency result;
  sentence-transformers' own guidance recommends torch for larger batches. Indexing runs at
  `bs=32` (throughput), where the kernel-fusion advantage shrinks or inverts. Our own profile
  already showed torch at `bs=32` is the saturated optimum (`bs>=64` OOMs).
- **Scope (research).** SPLADE's ONNX export covers only the BERT encoder; its pooling stays
  in torch, and it is the lighter model. Any benefit is dense-only, and Qwen3 O4 fusion is
  weeks old (onnxruntime 1.25.0, March 2026) with no published parity data.

## Constraints

- Do not force `onnxruntime-gpu` or the `nvidia-*-cu12` libs into the core dependency set:
  they are heavy and, on a cu130 torch, risk destabilising the working GPU path.
- Any backend selection must fall back to the torch path on any import/export/provider
  failure, logged (no silent swallow), so a misconfigured ONNX backend never breaks indexing.
- Adoption as the default must be gated on a measured, regression-free win (throughput at the
  real `bs=32` plus an embedding-parity check), which cannot be obtained cleanly on this
  cu130 machine today.

## Implementation

Deliver the backend as a **configuration seam, default torch**, with the heavy ONNX
dependencies left optional and operator-provided. `EmbeddingModel` reads a `dense_backend`
config knob (`VAULTSPEC_RAG_DENSE_BACKEND`, values `torch` | `onnx`, default `torch`). When
`onnx` is selected it constructs the dense `SentenceTransformer` with `backend="onnx"`,
`provider="CUDAExecutionProvider"`, and the cached O4 file; on any failure (missing
`optimum`/`onnxruntime-gpu`, export error, provider load failure) it logs a warning and falls
back to the torch construction. The sparse SPLADE path stays on torch. No ONNX dependency is
added to the project; selecting `onnx` requires the operator to have installed
`sentence-transformers[onnx-gpu]` in an onnxruntime-compatible CUDA environment. The
parity-and-throughput benchmark that would justify flipping the default on is deferred until
onnxruntime ships a CUDA-13 build (removing the dual-CUDA fragility); the seam makes that a
one-line config change when it does.

## Rationale

The seam is the only change that satisfies "deliver the ONNX-O4 lever" without violating
"eliminate all regression". The feature (operator-selectable ONNX dense backend with a safe
fallback) is delivered and testable now; the heavy, fragile cu12-alongside-cu13 dependency
stack and the unproven large-batch benefit are kept out of the default path. The empirical
spikes are decisive: ONNX-O4 on GPU is reachable here only through a dual-CUDA bundle that
endangers the working torch, and the speedup is in a batch regime we do not use. Shipping the
seam (zero core deps, tested fallback) and deferring activation is the honest, low-risk
delivery; forcing adoption now would be speculative and risk a regression.

## Consequences

Gains: the backend is operator-selectable today and trivially default-able later; zero new
core dependencies; the fallback is tested so a misconfigured backend degrades rather than
breaks. Costs and honesty: the ONNX-active path is not GPU-validated on this cu130 machine
(the spikes hit the CUDA-12/13 wall and the `optimum[onnxruntime-gpu]` stack), so it ships
experimental, gated behind the flag, with the parity/throughput gate to run in a
CUDA-12-compatible or future CUDA-13-onnxruntime environment. The expected benefit at `bs=32`
remains unproven and, per the research, likely small; this ADR does not claim a speedup, only
a ready, safe seam. Revisit and benchmark when onnxruntime supports CUDA 13.

## Codification candidates

- **Rule slug:** `embedding-backend-falls-back-to-torch`. Any non-default embedding backend
  (ONNX, OpenVINO) must degrade to the torch construction on any import/export/provider
  failure, logged, so a misconfigured backend never breaks indexing or search.
