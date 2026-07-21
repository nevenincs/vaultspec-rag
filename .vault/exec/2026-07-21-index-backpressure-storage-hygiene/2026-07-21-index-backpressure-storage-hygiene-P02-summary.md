---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# `index-backpressure-storage-hygiene` `P02` summary

## Description

Structured job errors and stall surfacing. New torch-free
`_job_errors.py` taxonomy; `error_kind` stamped on failed job records;
service-computed `stalled` flag on `/jobs` records plus stalled count and
error-kind histogram in the summary; bounded jobs rollup on `/health`;
CLI renders from the shared fields and the disk-full string match is
gone.

- Created: `src/vaultspec_rag/_job_errors.py`
- Modified: `src/vaultspec_rag/jobs.py`,
  `src/vaultspec_rag/server/_routes_jobs.py`,
  `src/vaultspec_rag/server/_routes.py`,
  `src/vaultspec_rag/server/_lifespan.py`,
  `src/vaultspec_rag/cli/_service_jobs.py`,
  `src/vaultspec_rag/tests/test_jobs_unit.py`,
  `src/vaultspec_rag/tests/test_server_routes.py`

Verification: registry/route/CLI suites green (33 + 66).
