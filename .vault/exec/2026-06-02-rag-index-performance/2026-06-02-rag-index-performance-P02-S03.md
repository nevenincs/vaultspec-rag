---
tags:
  - '#exec'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S03'
related:
  - "[[2026-06-02-rag-index-performance-plan]]"
---

# Add a single dedicated GPU consumer thread draining a bounded queue that owns the gpu_lock, with sentinel shutdown, exception re-raise, and bounded waits

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add a single dedicated GPU consumer thread that drains a bounded queue, owns the gpu_lock, and encodes dense then sparse per batch while the producer feeds it.
- Shut down with a sentinel, re-raise consumer-thread exceptions in the main thread, and bound every shutdown wait so a wedged consumer aborts instead of hanging the writer lock.

## Outcome

The GPU is saturated during chunking instead of idling; failures fail loud, not hang.

## Notes

Code review (C1/H1/H2) caught an unguarded sentinel put + unbounded join hang vector; fixed with liveness-guarded timed put + deadline-bounded join that escalates to a raise.
