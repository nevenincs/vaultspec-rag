---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:969ff9911f9e23fd5c06457f157713e11e9a8b3ee344f4045e8a9c258c9e20f1'
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
