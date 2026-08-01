---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:3eacf0ff0f764d24d6c1454bb738c739a6d183d4ada26dc943d90ac4569a3242'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# `index-cuda-ceiling` `P03` summary

All six Steps (`S10`-`S15`) complete. Each index job now enforces its own
lock-bracketed forward peak, net of the resident-model baseline, instead of a
process-global allocation high-water shared across concurrent jobs.

- Modified: `src/vaultspec_rag/memory_probe.py`
- Modified: `src/vaultspec_rag/embeddings.py`
- Modified: `src/vaultspec_rag/service.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

The phase re-scopes the CUDA peak measurement to the serialised GPU critical
section, keeping job concurrency intact. A bare rebase-and-read bracket
(`cuda_forward_peak_capture`, no allocator cache flush) wraps the lock-held
dense and sparse forwards; a thread-local recorder routes each bracket's
reading into the owning job's `MemoryBudget` as a maximum across its
brackets. Checkpoints - including the non-forward producer/consumer queue
waits where the field failures surfaced - enforce that captured value, and no
enforcement path reads the process-global allocator high-water any more (the
process-wide measurement helper was removed; the bracket is the single
sanctioned reader).

The resident-model baseline is sampled as a lock-guarded monotonic maximum
after every model load, including the lazily-loaded reranker that loads
outside the GPU lock, and is subtracted from BOTH sides of the ceiling
comparison. A captured peak is absolute (a post-rebase counter starts at the
resident models), so single-side subtraction would double-count the models
and covertly tighten the ceiling; the symmetric form is arithmetically
equivalent to the absolute comparison while the failure detail reports
indexing demand against indexing headroom.

One deviation from the plan's locators: the capture bracket landed in
`src/vaultspec_rag/embeddings.py` rather than the streaming module named by
`S12`, because a concurrent session held that file dirty. The placement is
equivalent - the dense on-device encode body executes entirely within the
caller's GPU-lock hold, and the sparse lock acquisition already lives in the
embeddings module - so the streaming file needed no edit.

Verification: full unit suite 2329 passed; lint, type, and citation gates
clean on every file this phase touched; the `P04` guard proofs exercised the
new enforcement in both directions.
