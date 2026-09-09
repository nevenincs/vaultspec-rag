---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:c47331ee7675af24176ec099a169269afe5f6151793734ee87c5a1bb4b0094e3'
step_id: 'S01'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Make the qdrant readiness wait treat observable recovery progress as liveness, keeping the existing fixed budget as a hard ceiling

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Changes

- `M` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `M` `docs/configuration.md`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-complexity` -> `pass`
- `verify:` `just check-nesting` -> `pass`
- `verify:` `just check-size` -> `pass`
- `verify:` `just check-markdown` -> `pass`
- `verify:` `just check-links` -> `pass`
