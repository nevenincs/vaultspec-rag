---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S17'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Replace the SPLADE densify-and-loop conversion with a single coalesced sparse-tensor pass

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- Replace the SPLADE conversion that densified [batch x vocab] and looped
  per row with a single coalesced-COO (or batched nonzero) pass - two
  device-to-host transfers per batch instead of two GPU syncs per row.

## Outcome

Conversion parity proven against a naive reference for dense, COO, and CSR
inputs including all-zero rows. This conversion ran inside the GPU lock on
every index slice, so the lock hold shrinks too.

## Notes
