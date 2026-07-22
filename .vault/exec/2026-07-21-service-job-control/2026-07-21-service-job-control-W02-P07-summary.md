---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W02.P07` summary

Production-facade integration now proves indexing control acknowledgement is a
real resource boundary rather than a state-only promise.

- Modified: `src/vaultspec_rag/tests/integration/test_index_job_control.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s17-execution-audit.md`

## Description

Vault and code attempts run through the public compatibility facade, canonical
manager, production registry, cached CUDA model, embedded local Qdrant, real
indexers, dedicated limiter, spawn workers, and sole code GPU consumer. Pause is
acknowledged only after task, worker, limiter, lease, writer, pipeline, process,
and consumer ownership has cleared. Resume keeps the logical job ID, creates a
fresh reconcile attempt, and converges real collection payloads and metadata.

Cancellation is absorbing and produces no later canonical progress, Qdrant
point, payload, or metadata writes after acknowledgement. A real Qdrant schema
failure remains `failed` when cancellation is pending and still releases the
complete attempt lifecycle. Test teardown follows the same safety contract: it
fails closed and refuses to close stores or reset ownership after a bounded join
failure.

All seven prior target cases, four new managed-facade cases, and ten focused
worker/GPU/registry/facade boundary regressions passed. Ruff, ty, BasedPyright,
formatting, collection, and diff hygiene passed. Independent review approved at
Critical 0 and High 0 with no remaining findings.
