---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:9a43bd850cefc5ad80e08d0216e601e09ce40a5119264813bbd2fd4bf2e2ff57'
step_id: 'S08'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Collapse PreprocessMode to a two-state on/off by removing the unsandboxed literal, the PREPROCESS_UNSANDBOXED EnvVar, and the unsandboxed arm of the preprocess_mode property, keeping PREPROCESS=off as the kill switch

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Collapse `PreprocessMode` to `Literal["default", "off"]` and `_VALID_PREPROCESS_MODES` to match.
- Delete `EnvVar.PREPROCESS_UNSANDBOXED` and the unsandboxed arm of the `preprocess_mode` property; `VAULTSPEC_RAG_PREPROCESS=off` remains the kill switch, read live.

## Outcome

Two-state mode resolves from one env var plus the configured default.

## Notes

None.
