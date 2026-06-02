---
tags:
  - '#exec'
  - '#onnx-encoder-backend'
date: '2026-06-02'
step_id: 'S02'
related:
  - "[[2026-06-02-onnx-encoder-backend-plan]]"
---

# Add a backend-aware dense loader that selects ONNX on CUDAExecutionProvider when configured and falls back to torch on any failure, logged

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- Add `EmbeddingModel._load_dense_model`: when `dense_backend == onnx`, construct the dense SentenceTransformer with `backend=onnx` on `CUDAExecutionProvider` using the cached O4 file (best-effort `onnxruntime.preload_dlls` via dynamic import); on any failure log a warning and fall back to the torch construction.

## Outcome

ONNX is opt-in and degrades to torch on missing optimum/onnxruntime, export error, or provider load failure (e.g. the onnxruntime CUDA-12 vs torch CUDA-13 mismatch).

## Notes

onnxruntime is imported dynamically (optional, operator-provided dependency); no ONNX dependency added to the project core.
