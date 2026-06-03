---
tags:
  - '#plan'
  - '#onnx-encoder-backend'
date: '2026-06-02'
tier: L2
related:
  - '[[2026-06-02-onnx-encoder-backend-adr]]'
  - '[[2026-06-02-onnx-encoder-backend-research]]'
---

# `onnx-encoder-backend` `onnx dense backend seam` plan

### Phase `P01` - backend seam

Add a default-torch dense-backend config knob and an ONNX loader that falls back to torch on any failure.

- [x] `P01.S01` - Add dense_backend and dense_onnx_file config knobs defaulting to torch with env overrides; `src/vaultspec_rag/config.py`.
- [x] `P01.S02` - Add a backend-aware dense loader that selects ONNX on CUDAExecutionProvider when configured and falls back to torch on any failure, logged; `src/vaultspec_rag/embeddings.py`.

### Phase `P02` - verify

Test the config default/override and the real-GPU onnx-to-torch fallback.

- [x] `P02.S03` - Add a unit test for the config default and override and a real-GPU test that the onnx backend degrades to torch and still embeds; `src/vaultspec_rag/tests/`.

## Description

Implements the onnx-encoder-backend ADR: a default-torch dense-encoder backend seam. `P01`
adds the `dense_backend` / `dense_onnx_file` config knobs and a backend-aware dense loader in
`EmbeddingModel` that selects the ONNX backend on `CUDAExecutionProvider` when configured and
falls back to torch on any failure (missing optimum/onnxruntime, export error, provider load
failure). `P02` tests the config default/override and validates on real GPU that selecting
`onnx` without the optional deps degrades to torch and still embeds. No ONNX dependency is
added to the project; the ONNX path is experimental and opt-in. Activation/benchmarking is
deferred per the ADR until onnxruntime ships a CUDA-13 build.

## Steps

## Parallelization

`P01` before `P02`. Within `P01`, the config knobs (`S01`) land before the loader (`S02`)
that reads them. `P02` follows the implementation.

## Verification

- Every Step `P01.S01` through `P02.S03` is closed.
- The config default is `torch` and the env var overrides it (unit test).
- On real GPU, selecting `dense_backend=onnx` without the optional deps degrades to torch and
  still produces embeddings of the right dimension (no crash).
- `ruff` and `ty` clean; no ONNX dependency added to the project core.
