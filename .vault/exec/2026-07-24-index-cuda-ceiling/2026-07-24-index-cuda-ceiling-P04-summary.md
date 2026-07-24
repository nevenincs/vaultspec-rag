---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# `index-cuda-ceiling` `P04` summary

## Summary

Phase P04 verified the CUDA-ceiling work and closes the plan at 19/19.

The guard proofs (S16 cross-job contamination, S17 baseline double-count) were
each observed failing for their intended reason and then passing, both
directions recorded in their step records. The full unit suite (2329) and the
citation gate are clean, and 28 GPU integration tests exercise the captured-peak
enforcement against real models on the RTX 4080.

S19 confirmed the fix live: a fresh service on shipped defaults ran a
feature-profile rebuild with ZERO `cuda_memory_ceiling` failures, and the
document corpus that had never once indexed embedded 418 sections. Full-corpus
completion was interrupted by concurrent cross-tenant load on the shared daemon,
not by the ceiling - the motivation for the sibling service-quiesce feature.

Two follow-ups are recorded in the S19 notes: `corpus_limit_exceeded` on the
`embedded-local` profile via the allocated corpus-dimension projection, and
whether the auto-derived ceiling should key off free device memory rather than
total on a shared desktop GPU (the ~6.5 GiB desktop baseline observed during
S19 is not subtracted today).

## Description
