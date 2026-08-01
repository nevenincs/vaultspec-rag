---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:4f39e64a7ab39d01c5001b25b3a97969eccf20d3e3dfaf15cb72cb8e07c347e4'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# `index-backpressure-storage-hygiene` `P07` summary

## Description

Shared-service protection from test runs. Session-scoped autouse
isolation fixture (structural machine-singleton isolation; fixed a live
victim test on landing); terminate tripwire refusing machine-global stops
from unisolated pytest contexts; persisted active-jobs snapshot with
`interrupted` restore at daemon startup so killed jobs never vanish.

- Modified: `src/vaultspec_rag/tests/conftest.py`,
  `src/vaultspec_rag/cli/_service_stop.py`, `src/vaultspec_rag/jobs.py`,
  `src/vaultspec_rag/server/_lifespan.py`,
  `src/vaultspec_rag/tests/test_jobs_unit.py`

Verification: jobs-unit suite green (34); formerly-failing qdrant CLI
test passes under the new isolation.
