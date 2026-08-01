---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:9a1de434471646710837cac03d36bb645524c2e86953ec4cd4e88674d4f0a3b2'
step_id: 'S38'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Extract canonical enums, immutable resources, outcomes, and serialization into a focused model module while preserving public imports using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/job_models.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Extract canonical job enums, frozen resources, outcomes, JSON serialization, specification validation, work identity, and capability derivation into `src/vaultspec_rag/job_models.py`.
- Import and re-export the canonical types from `src/vaultspec_rag/jobs.py` as the same class objects while retaining persistence, manager, runtime, logging, and legacy compatibility behavior in place.
- Add an imported-production regression in `src/vaultspec_rag/tests/test_jobs_unit.py` that verifies identity for every canonical model export.

## Outcome

`W01.P18.S38` is complete. The canonical service job model now has one dependency-light source, and every established import through `vaultspec_rag.jobs` remains identity-compatible. The focused job-control and job-manager suite, including all real-filesystem managed persistence integrations, passed 73 tests.

## Notes

- Semantic discovery timed out, so execution used the documented `rg` and direct-read fallback.
- Ruff format and check, ty, strict BasedPyright, diff hygiene, the focused identity regression, and the mandatory safety and intent review all passed.
- Plan and feature validation passed after assigning the inserted modularization phase its unique `W01.P18` display path; the plan checker retains only the intentional non-monotonic Step-order warning for inserted S38-S40 work.
- The test run reported only existing third-party deprecation warnings; no tests were skipped and no persistence or manager extraction was started.
