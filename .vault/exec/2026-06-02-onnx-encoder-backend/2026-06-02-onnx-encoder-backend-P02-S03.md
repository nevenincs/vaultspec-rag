---
tags:
  - '#exec'
  - '#onnx-encoder-backend'
date: '2026-06-02'
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

The onnx-active GPU path itself is not validated on this cu130 machine (CUDA-12/13 wall); it ships experimental per the ADR, with the parity/throughput gate deferred to a compatible environment.
