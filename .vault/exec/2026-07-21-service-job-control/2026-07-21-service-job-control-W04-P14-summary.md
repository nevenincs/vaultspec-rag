---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W04.P14` summary

Completed singular CLI job registration, six exact-resource controls, and
real-server human and JSON verification while preserving plural collection
behavior.

- Modified: `src/vaultspec_rag/cli/_app.py`
- Modified: `src/vaultspec_rag/cli/_service_jobs.py`
- Modified: `src/vaultspec_rag/tests/integration/test_service_job_control.py`
- Created: S29 through S31 execution and audit records.

## Description

Operators can show, pause, resume, stop, retry, and delete one job beneath the
singular `server job` group; `server jobs` remains the collection view. Human
commands resolve one unique prefix before exact access. JSON requires exact
identifiers and emits one structured outcome per tested exit path. Desired
state changes carry positive revisions, idempotent replays remain successful,
and force requests preserve the service's unsupported capability response.
