---
generated: true
tags:
  - '#index'
  - '#onnx-encoder-backend'
date: '2026-06-02'
related:
  - '[[2026-06-02-onnx-encoder-backend-P01-S01]]'
  - '[[2026-06-02-onnx-encoder-backend-P01-S02]]'
  - '[[2026-06-02-onnx-encoder-backend-P02-S03]]'
  - '[[2026-06-02-onnx-encoder-backend-adr]]'
  - '[[2026-06-02-onnx-encoder-backend-plan]]'
  - '[[2026-06-02-onnx-encoder-backend-research]]'
---

# `onnx-encoder-backend` feature index

Auto-generated index of all documents tagged with `#onnx-encoder-backend`.

## Documents

### adr

- `2026-06-02-onnx-encoder-backend-adr` - `onnx-encoder-backend` adr: `onnx-o4 dense encoder backend behind a flag with torch fallback` | (**status:** `accepted`)

### exec

- `2026-06-02-onnx-encoder-backend-P01-S01` - Add dense_backend and dense_onnx_file config knobs defaulting to torch with env overrides
- `2026-06-02-onnx-encoder-backend-P01-S02` - Add a backend-aware dense loader that selects ONNX on CUDAExecutionProvider when configured and falls back to torch on any failure, logged
- `2026-06-02-onnx-encoder-backend-P02-S03` - Add a unit test for the config default and override and a real-GPU test that the onnx backend degrades to torch and still embeds

### plan

- `2026-06-02-onnx-encoder-backend-plan` - `onnx-encoder-backend` `onnx dense backend seam` plan

### research

- `2026-06-02-onnx-encoder-backend-research` - `onnx-encoder-backend` research: `onnx-o4 encoder backend for the embed stage`
