---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:e961f6c9c17b2f286478b19618a203e51c990c577f48fae0e16dfaf2ddbd77aa'
step_id: 'S13'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Propagate run control through code producers, process-pool work, the single GPU consumer, bounded queues, and consumer shutdown using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Thread backward-compatible `RunControl` defaults through codebase scan,
  hashing, chunking, embedding, full-index, incremental-index, and scoped-index
  producers.
- Poll process futures and bounded queue operations every 100 ms, cancel queued
  futures on unwind, and join spawned CPU workers through executor ownership.
- Keep the token in the parent process and the sole GPU consumer thread; never
  serialize it, the model, Torch, or CUDA state into worker processes.
- Make consumer shutdown bounded and authoritative, preserving application,
  pool, and control exception precedence after cleanup.
- Defer control across destructive replacement paths until S14 installs their
  explicit protected spans, while leaving convergent publication interruptible.

## Outcome

Codebase indexing now observes pause and cancel throughout producer work,
process-pool waits, bounded queue backpressure, slice publication, and consumer
shutdown. Control signals unwind only after queued work is cancelled and owned
workers and the consumer are joined; a live consumer, real consumer failure, or
fatal progressed pool failure cannot be misreported as successful control.

Verification passed: 123 focused unit tests, 20 real codebase integration tests,
2 real GPU producer/consumer integration tests, 3 centralized-Torch architecture
tests, serial and two-worker real control probes, import/no-op-default checks,
Ruff, Ruff format, ty, BasedPyright, and `git diff --check`. Independent review
closed one Critical and two High race findings and ended at Critical 0 / High 0.

## Notes

Semantic RAG refresh was not retried because the execution context records a
CUDA OOM for that refresh path; implementation grounding used the complete
source, governing ADR/research/reference documents, and direct searches. No
temporary diagnostic files remain. S14 retains ownership of explicit
destructive publication protection, and S15 retains integration-test additions.
