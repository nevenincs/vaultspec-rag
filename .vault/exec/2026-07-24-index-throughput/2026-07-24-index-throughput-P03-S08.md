---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S08'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# adopt the bounded-queue producer/consumer pattern for the document encode path with sentinel shutdown and time-bounded joins

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

- Record written after the fact from the landed change; the work shipped in
  commit `87890030`, reusing the writer machinery S07 added.
- Hand each file's slice upsert, ledger confirmation, and after-store budget
  sample to the single FIFO writer thread, so slice N+1's encode and its
  budget/reserve accounting overlap slice N's storage I/O.
- Close the writer before the file's metadata is returned, so a write
  failure fails that file's run before any terminal metadata publish, and
  confirmations land in slice order.
- Leave encode on the calling thread and the per-slice cache-flush cadence
  unchanged.

## Outcome

Landed. The document path shares one writer thread with the vault path and
keeps one GPU consumer; the shutdown discipline (timed sentinel put,
bounded join, raise on a wedged store call) is the shared writer's, so it is
covered by the same guard tests as S07.

Deliberately not folded in: hook-extract prefetch (overlapping the next
file's subprocess extract with the current encode). It would move extraction
ahead of the per-file checkpoint and budget boundaries and needs its own
design.

## Notes

- No throughput number is recorded here. The measured 4,469 s document
  rebuild stage in the research is the pre-change baseline; no post-change
  document rebuild was timed in this Step.
- This record was scaffolded during the plan closeout; its evidence is the
  commit diff and message.
