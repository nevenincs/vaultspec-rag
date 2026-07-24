---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S12'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# capture the allocation high-water inside the gpu_lock forward bracket in the shared encode path

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Place the `cuda_forward_peak_capture` bracket inside the lock-held forward paths in `src/vaultspec_rag/embeddings.py`: the on-device dense encode (which the streaming caller invokes while holding `gpu_lock`) and the sparse encode's own `with gpu_lock:` block.
- Leave the unserialised no-lock sparse branch and the CPU-output dense path unbracketed: without the lock a rebase could race a concurrent bracket.

## Outcome

Every serialised indexing forward rebases and reads the peak counter inside the critical section, so the captured value is that forward's own demand and never a sibling's. The capture also completes on an exceptional exit, so an allocator OOM still records the demand that triggered it.

## Notes

The planned locator for this step was `src/vaultspec_rag/indexer/_streaming.py`, but that file is held dirty by a concurrent session. The bracket landed in `src/vaultspec_rag/embeddings.py` instead, which is equivalent: the dense on-device encode body executes entirely within the caller's `gpu_lock` hold, and the sparse lock acquisition already lives in `embeddings.py`. No edit to `_streaming.py` was made or needed.
