---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-07-27'
body_hash: 'sha256:4d36e3220985d95d2a6402c90f779e98a43ea95cb61831140dd1432ad2f53108'
step_id: 'S03'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

## Description

### Scope

- `src/vaultspec_rag/config.py`

- Register `QDRANT_QUANTIZATION` environment variable under `EnvVar` StrEnum.

- Enlist the environment variable under the configuration wrapper's mapping index `_ENV_OVERRIDE_MAP`.

- Provide default setting `qdrant_quantization` mapping to `None` in `_RAG_DEFAULTS`.

## Outcome

- Quantization configuration options can be specified at deploy/runtime via environment variables.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
