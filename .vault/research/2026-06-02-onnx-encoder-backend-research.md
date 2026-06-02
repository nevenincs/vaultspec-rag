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

## Recommendation (input to the ADR)

Scope to **dense-only**, behind an **experimental, off-by-default** config flag with a torch
fallback, and **validate before trusting**. SPLADE ONNX buys little (pooling stays in torch;
lighter model). The headline speedup is for a batch regime we are not in, and the Qwen3 O4
path is weeks old with no published parity. Therefore the deliverable is the **complete,
gated backend plus the evidence to decide its default**: implement
`VAULTSPEC_RAG_DENSE_BACKEND=torch|onnx` (default `torch`), export+cache the O4 model, run an
embedding-parity gate, and benchmark embed throughput at the real `bs=32` against the torch
baseline. Adopt as default only if the benchmark shows a material, regression-free win;
otherwise ship it opt-in with the benchmark documenting why it stays off.

## Open questions for the ADR

- Are `onnxruntime-gpu >= 1.25.0` and a recent `optimum` installable in this uv environment
  with the existing CUDA torch build (cuDNN 9 match), and does Qwen3-Embedding-0.6B actually
  export with O4 here?
- Dense-only now, or leave a seam for SPLADE-encoder ONNX later?
- Where the parity gate lives (a new real-GPU test) and the cosine/top-k thresholds.
- Default-on vs opt-in is decided by the benchmark, not pre-committed.
