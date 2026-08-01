---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:98618b1a641c4af3d8b4a944d4a10a49bfdf61f348eca0d00aa82090a617c25d'
step_id: 'S05'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# carry the free-derived ceiling through the dispatch admission snapshot as a point-in-time diagnostic without changing enforcement

## Scope

- `src/vaultspec_rag/job_dispatch.py`

## Description

- Thread the new signature through `_admitted_resilience` in `src/vaultspec_rag/job_dispatch.py:301-317`: import `resident_cuda_baseline_mb` and pass `baseline_mb=resident_cuda_baseline_mb()`.
- Change no enforcement: the snapshot remains reported/persisted diagnostic only, and a comment states that it may legitimately differ from the later per-job enforcing derivation.

## Outcome

Dispatch admission snapshot computes the same absolute formula as a point-in-time diagnostic; divergence from the post-flush enforcing value is accepted per the decision record.

## Notes

`_admitted_resilience` runs before model loading, so its baseline reading is typically 0.0 there - another accepted source of diagnostic divergence.
