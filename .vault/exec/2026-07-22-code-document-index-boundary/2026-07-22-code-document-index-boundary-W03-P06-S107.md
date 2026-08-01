---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:85b85a3956676daa9d4effe0d3bbd25262c4421d42f9d48c87a5fe0171b1086f'
step_id: 'S107'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define and enforce a named document support profile at service job admission before GPU work

## Scope

- `src/vaultspec_rag/index_profiles.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Define independent document source, generated-chunk, weighted-byte, queue, host-memory, device-memory, and disk ceilings.
- Validate document policy and support admission before durable HTTP job creation and model loading.
- Require the exact admitted document preflight when activating a newly created job.

## Outcome

Unsupported document workloads fail model-free at service admission, while queued and restored attempts rediscover current scope before execution.

## Notes

Read-only status exposes each public domain's latest generation plus degraded failed, interrupted, or stalled work.
