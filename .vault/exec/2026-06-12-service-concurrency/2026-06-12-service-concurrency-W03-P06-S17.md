---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
body_hash: 'sha256:f4eac36ef85d999825398686fdc3c4bb1bef5f7b3a50909287674938297803d5'
step_id: 'S17'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Replace the SPLADE densify-and-loop conversion with a single coalesced sparse-tensor pass

## Description

### Scope

- `src/vaultspec_rag/embeddings.py`

- Replace the SPLADE conversion that densified [batch x vocab] and looped
  per row with a single coalesced-COO (or batched nonzero) pass - two
  device-to-host transfers per batch instead of two GPU syncs per row.

## Outcome

Conversion parity proven against a naive reference for dense, COO, and CSR
inputs including all-zero rows. This conversion ran inside the GPU lock on
every index slice, so the lock hold shrinks too.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
