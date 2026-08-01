---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:a6a25c45094ebc73d6871b9d5c24faeef1c8f446ab18c230ea330a2248c0f2b4'
step_id: 'S11'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Add checkpoints around vault phases and batches while protecting collection drop through valid publication using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add no-op-default run control to public, locked, scoped, and helper vault
  indexing seams.
- Check control at writer-lock, phase, per-file batch, storage mutation, and
  atomic metadata boundaries while balancing progress phases on every unwind.
- Forward the same token through all streaming embedding calls.
- Protect clean collection drop, replacement streaming, stale cleanup, and
  metadata publication as one indivisible cooperative-control span.
- Bound document preparation work, poll control while waiting, and cancel
  queued futures before releasing the writer lock on unwind.
- Verify static types, formatting, real control primitives, real-file parsing,
  atomic publication, and architecture invariants through independent review.

## Outcome

Vault indexing can now cooperatively unwind between safe phases and bounded
batches without changing unmanaged callers. Non-clean work remains interruptible
between convergent mutations. Clean rebuild requests are refused before collection
drop or deferred until a complete replacement and its metadata are published.

Ruff, Ruff formatting, ty, strict BasedPyright, and `git diff --check` passed.
All 18 focused production tests passed. A fresh-process production probe verified
torch-free imports, exact no-control defaults, real bounded parsing, pre-mutation
pause delivery, and deferred pause delivery after atomic metadata publication.
Independent re-review found no remaining Critical or High issues.

## Notes

The initial review found one High issue: `ThreadPoolExecutor` context shutdown
would have drained a corpus-sized queued parse set after control delivery. The
revision caps in-flight work at twice the worker count, polls every 100 ms,
cancels pending futures on unwind, and waits only for already-running tasks.

Semantic discovery reported no indexed source sections, so full-file inspection
and targeted source search grounded the change. The recorded CUDA OOM refresh was
not retried; real streaming/rebuild interruption coverage remains assigned to S12.
