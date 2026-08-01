---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:5e0ce8c30a56ae10d6aeaddec36b53ec52be6d195aaa00c07514579ddd41edd3'
step_id: 'S16'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# apply the existing flush-cadence throttle to the vault slice path, which currently empties the CUDA cache every slice

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Add the `vault_cache_flush_slices` knob (env-overridable) in `src/vaultspec_rag/config.py`, defaulting to 1.
- Thread `release_cache` through `_encode_and_upsert_vault_slice` and apply the last-slice-or-cadence rule in `_stream_encode_and_upsert_vault` in `src/vaultspec_rag/indexer/_streaming.py`, mirroring the codebase path's throttle (commit `c89b7b50`).

## Outcome

The vault path's CUDA cache flush is now cadence-controlled, but the default of 1 preserves the historical every-slice flushing byte-for-byte. COERCED CONSERVATIVE: the flip to a higher cadence is measurement-gated - per-slice flushing may be load-bearing against allocator fragmentation on a ceiling that counts reserved memory - and the gate (peak-reserved and OOM validation on real full rebuilds in a coordinated GPU window) is documented at the knob.

## Notes

The measured-run half of this step (re-tune under overlap and record the effect) is deliberately not done; it requires the GPU window and stays open.
