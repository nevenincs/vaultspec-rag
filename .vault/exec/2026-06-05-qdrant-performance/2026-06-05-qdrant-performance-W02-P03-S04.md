---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-06-30'
step_id: 'S04'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

# Configure scalar/product/turbo quantization in Qdrant collection creation

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Read `qdrant_quantization` value from configuration settings.
- Build corresponding quantization config objects for scalar (INT8), product (PQ, X16 compression ratio), or TurboQuant options.
- Pass the constructed quantization configuration option to `create_collection` keyword arguments.

## Outcome

- Newly created vector collections in Qdrant apply server-side quantization configs for optimal RAM and search efficiency.
