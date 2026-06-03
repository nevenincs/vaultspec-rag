---
tags:
  - '#research'
  - '#onnx-encoder-backend'
date: '2026-06-02'
related:
  - "[[2026-06-02-rag-index-performance-research]]"
---

# `onnx-encoder-backend` research: `onnx-o4 encoder backend for the embed stage`

## Problem

The rag-index-performance profile established that embedding dominates indexing wall-clock
(~17 min for 112k chunks at the optimal `bs=32`), with dense Qwen3 + sparse SPLADE on one
16 GB GPU. The documented next lever was an ONNX-O4 encoder backend (sentence-transformers
cites ~1.83x on short text). This document grounds whether and how to adopt it.

## Findings

### API (sentence-transformers >= 5.1.0)

Two-step: export once, then load by file. Dense:
`SentenceTransformer(model, backend="onnx")` then
`export_optimized_onnx_model(model, optimization_config="O4", model_name_or_path=...)`
(O4 = fp16 + extended graph fusions), then load with
`model_kwargs={"provider": "CUDAExecutionProvider", "file_name": "onnx/model_O4.onnx"}`.
Install extra `sentence-transformers[onnx-gpu]`. Source: SBERT efficiency docs; backends
landed in v5.1.0. Confidence: high.

### SPLADE / SparseEncoder also supports ONNX, but it is the wrong half

`SparseEncoder("naver/splade-v3", backend="onnx")` is supported, but the ONNX export covers
only the BERT encoder; `SpladePooling` (max-pool + ReLU over the 30k MLM head) stays in
torch. SPLADE-v3 is BERT-base scale (~110M params) versus Qwen3-0.6B (~600M, 1024-d), so the
dense pass dominates encode cost — a **dense-only** ONNX path captures most of any win. The
exact split is not published; it must be measured. Confidence: high on API + pooling caveat,
medium on the split.

### Qwen3 O4 fusion is brand new: requires onnxruntime-gpu >= 1.25.0

Qwen3 graph optimization was a hard `NotImplementedError` until onnxruntime PR #27556 (merged
2026-03-13), shipped in onnxruntime **1.25.0 (March 2026)** — it registers `qwen3` via the
GPT2 optimizer (RoPE/RMSNorm), adds RotaryEmbedding fusion. A recent `optimum` is also needed
(a raw-export "invalid unordered_map key" bug exists on optimum 1.25.3 stable, fixed on
master). A pre-built `onnx-community/Qwen3-Embedding-0.6B-ONNX` exists (fp16/q8) but advertises
no O4 variant and publishes no parity numbers. **Hard version gate: onnxruntime-gpu >=
1.25.0.** Confidence: high on the gate; medium on accuracy drift.

### onnxruntime-gpu + torch coexistence

Workable: onnxruntime-gpu 1.2x builds against CUDA 12 + cuDNN 9; torch >= 2.4 uses cuDNN 9, so
a CUDA-12/cuDNN-9 torch build pairs cleanly. Import torch before onnxruntime (or call
`onnxruntime.preload_dlls()`) to avoid duplicate-DLL conflicts. onnxruntime's CUDA EP keeps a
separate VRAM arena (cap with `gpu_mem_limit`); on 16 GB with tiny weights (Qwen3 ~1.2 GB,
SPLADE ~0.13 GB) this is fine but adds overhead alongside the torch CrossEncoder. Confidence:
high.

### The decisive risk: wrong batch regime

SBERT's ~1.83x is **GPU + short text + batch \<= 4** (a latency regime); the decision
flowchart recommends torch bf16 for larger batches. Indexing 112k chunks is a **large-batch
throughput** job — exactly where O4's kernel-fusion advantage shrinks or inverts (at high
batch the work is compute-bound and torch's fused CUDA kernels are already efficient). No
independent CUDA O4-vs-fp16 benchmark for Qwen3-class embedding models at indexing batch
sizes was found. Realistic expectation on a 4080 at `bs=32`: modest at best, possibly
negligible. This must be measured at the real indexing batch size, not assumed from the
headline. Confidence: high.

### Parity and ops

No official Qwen3 O4 parity figure exists; fp16 ONNX vs fp16 torch is normally >= 0.9999
cosine, but O4's fusions on the fresh Qwen3 path carry unquantified drift risk. Gate on a
self-run check (mean cosine >= 0.999, min >= 0.99, plus top-k overlap on a query set via the
existing quality/benchmark harness). The O4 file caches to disk (~1.2 GB, fp16-sized);
first export needs optimum (+ network for a hub id). Everything must sit behind a config flag
(default torch) with a logged fallback on any ONNX init/export failure. Confidence: high on
mechanism, medium on drift.

## Hands-on verification (2026-06-03)

Ran the actual attempt on the RTX 4080 SUPER (cu130 torch), correcting an earlier wrong
assumption and reaching the decisive end-to-end finding:

- **CUDA 13 onnxruntime exists and coexists cleanly — earlier "cu12-only" claim was wrong.**
  The stable `onnxruntime-gpu` is CUDA-12 (its `providers_cuda.dll` needs `cublasLt64_12.dll`)
  and collides with cu130 torch's cuDNN (`WinError 127`). But the **CUDA-13 nightly**
  (`onnxruntime-gpu 1.27.0.dev`, from the `ort-cuda-13-nightly` index) reuses torch's cu13
  CUDA/cuDNN ("Skip loading CUDA and cuDNN DLLs since torch is imported") — `CUDAExecutionProvider`
  is active and torch keeps working in the same process. The CUDA version is **not** the blocker.
- **The real blocker is the sentence-transformers / optimum ONNX backend not supporting Qwen3
  end-to-end yet:**
  - O4 graph optimization raises `NotImplementedError: ONNX Runtime doesn't support the graph optimization of qwen3 yet` from `optimum-onnx 0.1.0` (its supported-model list excludes
    qwen3 — separate from onnxruntime's own qwen3 optimizer support).
  - Base ONNX (no O4) exports and loads on CUDA, but **inference crashes**:
    `optimum/onnxruntime/base.py:_prepare_io_binding -> input_shape = model_inputs[input_name].shape -> AttributeError: 'NoneType' object has no attribute 'shape'` — the exported Qwen3 graph expects an input (e.g. `position_ids`) that the ST
    ONNX forward leaves `None`.
- **Torch baseline (measured, same machine/sample):** ~230-254 chunks/s at `bs=32` for the
  dense Qwen3 encode. No ONNX throughput or parity number exists **because the ONNX path
  cannot produce Qwen3 embeddings at all** in the current stack (it crashes before any vector
  is returned). So there is nothing to compare yet — torch is the only working dense path.

Follow-up attempts confirmed it is ST-side and not fixable operator-side:
`use_io_binding=False` turns the io-binding crash into the explicit
`ValueError: Input position_ids is required by model but not provided` (ST's ONNX forward
never supplies `position_ids`), and the **prebuilt** `onnx-community/Qwen3-Embedding-0.6B-ONNX`
fails identically — so it is not our export. The required ONNX stack also pins
`optimum-onnx 0.1.0`, which downgrades `transformers` 5.9 -> 4.57 (conflicting with the
project), and a control run on a supported BERT model could not complete in that mutated env.

Net: this is not a CUDA-environment problem and not a "wrong batch regime" judgement call —
it is a hard integration gap (optimum-onnx + ST do not yet support Qwen3-Embedding inference
or O4) compounded by version conflicts with the project's pinned stack. A clean onnx-vs-torch
comparison therefore needs a separate, version-matched environment, not mutation of this
project's venv. Adoption is blocked upstream, not by our code. Torch is the only working dense
path (measured baseline ~230-254 chunks/s at bs=32).

## Recommendation (input to the ADR)

Scope to **dense-only**, behind an **experimental, off-by-default** config flag with a torch
fallback. The deliverable is the **complete, gated seam**:
`VAULTSPEC_RAG_DENSE_BACKEND=torch|onnx` (default `torch`) that degrades to torch on any
failure. Activation is **blocked upstream**, not merely deferred: the hands-on verification
shows the ST/optimum ONNX backend cannot run Qwen3-Embedding today (base inference crashes in
optimum io-binding; O4 unsupported for qwen3). The seam's fallback is therefore not just a
safety net — it is the *current behaviour* when `onnx` is selected. The throughput/parity
gate that would justify flipping the default on can only run once `optimum-onnx` adds Qwen3
support (inference + O4); the seam makes that a one-line config change when it lands. The CUDA
environment is **not** a blocker — the onnxruntime CUDA-13 nightly coexists with cu130 torch.

## Open questions for the ADR

- Are `onnxruntime-gpu >= 1.25.0` and a recent `optimum` installable in this uv environment
  with the existing CUDA torch build (cuDNN 9 match), and does Qwen3-Embedding-0.6B actually
  export with O4 here?
- Dense-only now, or leave a seam for SPLADE-encoder ONNX later?
- Where the parity gate lives (a new real-GPU test) and the cosine/top-k thresholds.
- Default-on vs opt-in is decided by the benchmark, not pre-committed.
