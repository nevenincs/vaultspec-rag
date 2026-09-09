---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:b8791b435f9fdcd13f00575d4b1463c76fe80a36fad782c3e55131fe3e93c2d5'
step_id: 'S02'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving a child still recovering collections survives past the old fixed budget

## Scope

- `src/vaultspec_rag/tests/test_qdrant_supervise.py`

## Changes

- `A` `src/vaultspec_rag/tests/test_qdrant_supervise.py`
- `verify:` `pytest test_qdrant_supervise.py::TestProgressCountsAsLiveness` -> `pass`
