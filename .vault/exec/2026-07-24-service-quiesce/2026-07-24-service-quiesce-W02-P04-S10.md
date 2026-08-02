---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d5ab4439a12868f8888ff14237ffef99f69bf705aba7969b8af40145337a7fa9'
step_id: 'S10'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Create the serialized resource-quiesce controller with state transitions, epoch-scoped compute tickets, bounded drain acknowledgement and truthful safety snapshots

## Scope

- `src/vaultspec_rag/service_quiesce.py`

## Description

- Add the torch-free serialized controller and immutable state snapshots.
- Track epoch-scoped compute tickets under one condition lock.
- Require a bounded drain acknowledgement before GPU-residency release can become borrow-safe.
- Keep failed and warming transitions closed and unsafe.

## Outcome

The controller exposes only `running`, `pausing`, `quiesced`, and `warming` states.
Admission closes atomically with pause, and only a drained, explicitly acknowledged
transition can report `safe_to_borrow_gpu: true`.

Focused static validation passed: Ruff and `ty` both accepted the new module. The
mandatory review initially found a missing drain-acknowledgement precondition and
non-finite timeout validation; both were corrected and the re-review passed.

## Notes

No service, RAG endpoint, CUDA allocation, or GPU test was run. Registry integration
and controller behavior tests remain in their separately planned steps.
