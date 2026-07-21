---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add error_kind to job records with mapping in record_finish, and a computed stalled flag (running, non-waiting, progress age past threshold) on job snapshots

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

New torch-free `_job_errors.py` owns the shared taxonomy: `classify_error_text`
(disk_full via errno-28/WAL/optimizer/preflight markers, timeout, unavailable,
other), `remediation`, and `STALL_THRESHOLD_SECONDS`. `record_start` seeds
`error_kind: None`; `record_finish` stamps it from the error text and carries
it on the finished log event.

## Outcome

Committed as `feat(jobs): shared error taxonomy; error_kind stamped on failed job records (#242)`; covered by `TestJobErrorKind`.

## Notes

Text-derived classification keeps the registry decoupled from the store's
exception types while matching `_store_writes`' marker semantics.
