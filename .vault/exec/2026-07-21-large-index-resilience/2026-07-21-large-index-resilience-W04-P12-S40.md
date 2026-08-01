---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:637f113f7aa860a37d24528f78512841dc1a4e725c7a29197b63922ed0e6799c'
step_id: 'S40'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Define named managed-service and embedded-local profiles with benchmark-derived resource and corpus dimensions

## Scope

- `src/vaultspec_rag/index_profiles.py`

## Description

- Define closed managed-service and embedded-local profile names.
- Keep backend, RAM, disk, and corpus limits explicit and immutable.
- Partition source-code and document workload limits by typed index domain.
- Return stable typed refusal reasons for backend, host, disk, and corpus violations.

## Outcome

Index admission now resolves one named support contract with independent code and document dimensions. Unknown profiles and unsupported hosts fail closed through the shared job-error taxonomy.

## Notes

The profile contract landed in commit `4c9fe8cf`. The phase-boundary selection verified exact-limit admission and typed backend, RAM, disk, source, and generated-work refusal.
