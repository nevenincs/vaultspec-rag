---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-07-27'
step_id: 'S04'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

## Description

### Scope

- `src/vaultspec_rag/store.py`

- Read `qdrant_quantization` value from configuration settings.
- Build corresponding quantization config objects for scalar (INT8), product (PQ, X16 compression ratio), or TurboQuant options.
- Pass the constructed quantization configuration option to `create_collection` keyword arguments.

## Outcome

- Newly created vector collections in Qdrant apply server-side quantization configs for optimal RAM and search efficiency.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
