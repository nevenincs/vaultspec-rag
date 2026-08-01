---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:9e2c24a330ff2cace415f6a79fcfaf88ee745ea2267a5e64d912e491dcfb1b0b'
step_id: 'S21'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Add the exact canonical quiesce block to read-only service-state output by projecting the registry controller snapshot once

## Scope

- `src/vaultspec_rag/api.py`

## Description

Add the current controller snapshot to the canonical read-only service-state
projection. Render it once through `QuiesceSnapshot.as_envelope` beside the
existing project, watcher, and storage state.

## Outcome

Satisfied by `04660476`. The service-state payload carries the exact same
twelve-field controller vocabulary as health, with no duplicated state
derivation.

## Notes

The checked-in projection guard was inspected but not executed during this
acceptance. No service, RAG, CUDA, GPU, lint, or type-check command was run.
