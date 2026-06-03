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

Findings, measured hands-on (2026-06-03), supersede the initial CUDA-version concern:

- **Environment is NOT the blocker (corrected).** An earlier assumption that onnxruntime is
  CUDA-12-only was wrong. The stable `onnxruntime-gpu` is CUDA-12 and collides with cu130
  torch's cuDNN, but the **CUDA-13 nightly** (`onnxruntime-gpu 1.27.0.dev`, `ort-cuda-13-nightly`
  index) coexists cleanly: it reuses torch's cu13 CUDA/cuDNN, `CUDAExecutionProvider` is active,
  and torch keeps working in the same process. CUDA compatibility is solved.
- **The blocker is the ST/optimum ONNX backend not supporting Qwen3 end-to-end (measured).**
  O4 graph optimization raises `NotImplementedError` for qwen3 in `optimum-onnx 0.1.0`
  (qwen3 absent from its supported list), and base ONNX *inference* crashes in optimum
  io-binding (`_prepare_io_binding`: a `None` input such as `position_ids` -> `AttributeError`).
  The ONNX dense path cannot produce a single Qwen3 embedding today. This is an upstream gap,
  not our code.
- **Batch regime (research).** Even once it works, the ~1.83x is a batch\<=4 latency result;
  indexing runs at `bs=32` (throughput) where torch is already the saturated optimum
  (`bs>=64` OOMs) — so the expected win is small regardless.
- **Scope (research).** SPLADE's ONNX export covers only the BERT encoder (pooling stays in
  torch) and it is the lighter model, so any future benefit is dense-only.

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
breaks. Costs and honesty: the ONNX dense path **cannot run Qwen3-Embedding today** — proven
hands-on (base inference crashes in optimum io-binding on a `None` input; O4 unsupported for
qwen3 in `optimum-onnx 0.1.0`). The CUDA-13 nightly onnxruntime coexists with cu130 torch
(the environment is not the blocker), but the ST/optimum integration gap is. So selecting
`onnx` today simply degrades to torch (the tested behaviour), and no throughput/parity number
exists because the ONNX path returns no embedding. The expected benefit at `bs=32` is also
likely small (batch-regime). This ADR does not claim a speedup — only a ready, safe seam.
Revisit and run the parity/throughput gate when `optimum-onnx` adds Qwen3 support (inference

- O4).

## Codification candidates

- **Rule slug:** `embedding-backend-falls-back-to-torch`. Any non-default embedding backend
  (ONNX, OpenVINO) must degrade to the torch construction on any import/export/provider
  failure, logged, so a misconfigured backend never breaks indexing or search.
