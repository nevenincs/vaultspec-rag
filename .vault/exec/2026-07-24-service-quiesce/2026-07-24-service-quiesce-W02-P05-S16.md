---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S16'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# Ticketed search admission

## Description

Completed controller-ticket admission before search project or runtime ownership.

## Outcome

Search admission takes a controller ticket before project-slot or compute-runtime construction, and closed admission raises the retryable quiescing outcome instead of retaining GPU or project references.

## Evidence

`test_search_quiesce_admission.py` passed CPU-only proof that a pre-pause ticket prevents quiescence and that a quiesced search lease constructs no project, model, reranker, or CUDA state.

## Notes

No service process, CUDA allocation, or GPU test was run.
