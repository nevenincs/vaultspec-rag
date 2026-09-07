---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:c5002e881820ed2095b0cd00590de1af1614b0ec6001568365b08926b9631231'
step_id: 'S01'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Add full-reindex-required taxonomy and remediation

## Scope

- `src/vaultspec_rag/_job_errors.py`

## Changes

- `M` `src/vaultspec_rag/_job_errors.py`
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_jobs_lifecycle.py -q -p no:xdist` -> `pass`
