---
tags:
  - '#exec'
  - '#onnx-encoder-backend'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S01'
related:
  - "[[2026-06-02-onnx-encoder-backend-plan]]"
---

# Add dense_backend and dense_onnx_file config knobs defaulting to torch with env overrides

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add `dense_backend` (default `torch`) and `dense_onnx_file` (default `onnx/model_O4.onnx`) config knobs with `VAULTSPEC_RAG_DENSE_BACKEND` / `VAULTSPEC_RAG_DENSE_ONNX_FILE` env overrides.

## Outcome

The dense-encoder backend is operator-selectable; default behaviour is unchanged (torch).

## Notes

None.
