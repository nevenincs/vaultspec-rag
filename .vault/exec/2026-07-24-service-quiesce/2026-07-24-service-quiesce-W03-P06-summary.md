---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:02eb8b46432237686a804ef779fe1f8543aca58329462099309aacfb89500ebf'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` `W03.P06` summary

P06 is accepted from commits `0df85c2c`, `04660476`, and `9fc85828`.

- Modified: `src/vaultspec_rag/server/_routes.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/api.py`
- Modified: `src/vaultspec_rag/tests/test_service_quiesce_routes.py`
- Created: `src/vaultspec_rag/tests/test_quiesce_state_projections.py`
- Created: `src/vaultspec_rag/tests/test_jobs_quiesce_projection.py`

## Description

Authenticated pause and resume now expose one retryable service-owned failure
shape and one achieved shape. Health, jobs, and service-state project the same
twelve-field controller envelope directly from the registry. The checked-in
route proof uses a real persistence writer and filesystem failure to show
closed warming after an unpublished recovery write, followed by a repaired
same-ID attempt and exactly one recovered generation.

This summary closes only P06. P07 adapter acceptance remains incomplete because
S24 does not yet validate that `ok: true` also carries the requested achieved
controller state. S26 through S28 were correctly held until this authoritative
route vocabulary was accepted; they are now eligible as P07 work alongside the
S24 remediation. No W04 borrower work is authorized by this phase.

Acceptance was static. No service process, RAG endpoint, CUDA allocation, GPU
test, CPU test, negative mutation, lint, or type-check gate was run.
