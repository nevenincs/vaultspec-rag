---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S17'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# throttle the document per-file loop's cache release, which currently syncs the device every slice by defaulting release-cache on

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Add the `document_cache_flush_slices` knob (env-overridable) in `src/vaultspec_rag/config.py`, defaulting to 1.
- Pass a cadence-derived `release_cache` from the document per-file slice loop through `_encode_slice_through_writer` into `encode_and_upsert_document_slice` in `src/vaultspec_rag/indexer/_document_indexer.py`, releasing on file end or on the cadence boundary (commit `c89b7b50`).

## Outcome

The document per-file loop's every-slice cache release is now cadence-controlled with the default preserving current behavior byte-for-byte. The flip is measurement-gated on peak-reserved-memory and OOM validation in a coordinated GPU window, documented at the knob alongside the vault cadence.

## Notes

The cache flush stays on the encoding thread at the same boundary as before; only its frequency became configurable.
