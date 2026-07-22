---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S42'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Enforce hardware and backend profile admission at service job submission before GPU work

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Validate the configured code profile against immutable preflight measurements.
- Check backend, total RAM, and free disk before durable job creation.
- Revalidate managed attempts before model loading and GPU work.
- Preserve stable typed admission reasons through the HTTP jobs boundary.

## Outcome

Code job submission now fails before durable creation when its backend, host, disk, or source corpus is unsupported. Accepted work carries the exact preflight authority into dispatch, while generated-work ceilings remain enforced incrementally before queue admission.

## Notes

HTTP maps profile and corpus refusals to structured 422 responses and disk preflight failure to 507. A refused request leaves the canonical job manager empty.
