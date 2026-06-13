---
tags:
  - '#exec'
  - '#onnx-encoder-backend'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S03'
related:
  - "[[2026-06-02-onnx-encoder-backend-plan]]"
---

# Add a unit test for the config default and override and a real-GPU test that the onnx backend degrades to torch and still embeds

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add a unit test asserting the config default is torch and the env var overrides it, and a real-GPU integration test that selecting onnx without the optional deps falls back to torch and still produces embeddings of the right dimension.

## Outcome

Config seam + fallback validated: 2 unit + 1 real-GPU test green (no mocks).

## Notes

Hands-on verification (2026-06-03) corrected the original CUDA assumption: the onnxruntime
CUDA-13 nightly (1.27.0.dev) coexists cleanly with cu130 torch (reuses torch's cu13 cuDNN;
`CUDAExecutionProvider` active), so the environment is not the blocker. The real blocker is
upstream: `optimum-onnx 0.1.0` does not support qwen3 O4 (`NotImplementedError`) and base
ONNX inference of Qwen3 crashes in optimum io-binding (`_prepare_io_binding`, a `None` input).
So the ONNX dense path returns no embedding for our model today and there is no throughput or
parity number to report; selecting `onnx` degrades to torch (the tested behaviour). Torch
baseline measured ~230-254 chunks/s at bs=32. The benchmark venv was restored to the pristine
lockfile state afterward (extras removed, transformers 5.9.0). Revisit when optimum-onnx adds
Qwen3 support.
