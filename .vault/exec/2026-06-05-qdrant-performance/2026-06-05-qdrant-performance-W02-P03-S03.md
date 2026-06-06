---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
step_id: 'S03'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

# Add QDRANT_QUANTIZATION environment variable to config wrapper

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Register `QDRANT_QUANTIZATION` environment variable under `EnvVar` StrEnum.
- Enlist the environment variable under the configuration wrapper's mapping index `_ENV_OVERRIDE_MAP`.
- Provide default setting `qdrant_quantization` mapping to `None` in `_RAG_DEFAULTS`.

## Outcome

- Quantization configuration options can be specified at deploy/runtime via environment variables.
