---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S80'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify over-budget document workloads are refused at job admission before GPU work

## Scope

- `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`

## Description

- Submit an over-budget document job through the production attempt runner.
- Assert typed admission refusal before registry model load or project lease.
- Assert the configured extractor and durable project state remain untouched.

## Outcome

Document queue ceilings now have direct acceptance evidence at the job boundary.
The rejected attempt loads no model, opens no project, runs no extractor, and
creates no index state.

## Notes

Scoped Ruff and Ty checks passed. The real dispatch-path integration test passed
without using a GPU.
