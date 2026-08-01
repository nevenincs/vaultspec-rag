---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:46c040929eb083bc81bfe5791b348b725de9cbabb7c27450645bf71ad6874362'
step_id: 'S27'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Atomically publish metadata from ledger rows and preserve the last valid sidecar until replacement

## Scope

- `src/vaultspec_rag/indexer/_code_meta.py`

## Description

- Stream unique ordered ledger file states into a generation-specific temporary sidecar.
- Flush and fsync the complete JSON document before atomic replacement.
- Preserve the previous valid sidecar when iteration, validation, serialization, or replacement fails.
- Advance metadata publication only after the atomic replacement returns successfully.

## Outcome

Code metadata publication is atomic, row-streamed, generation-stamped, and retry-safe. Concurrent attempts use distinct temporary files, and an incomplete publication cannot replace or delete the last valid sidecar.

## Notes

The implementation landed earlier in the shared ledger integration and was reconciled here with P07 finalization. Real SQLite tests verified converged-row filtering, failure preservation, and overlapping atomic publications; the final P06 gate also exercised the integrated full and incremental paths.
