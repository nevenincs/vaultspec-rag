---
tags:
  - '#research'
  - '#server-bound-search-production-readiness'
date: '2026-06-11'
modified: '2026-06-30'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-06-05-qdrant-performance-adr]]'
  - '[[2026-06-07-sparse-search-latency-adr]]'
  - '[[2026-06-05-service-stress-watcher-adr]]'
  - '[[2026-06-02-index-gpu-pipeline-adr]]'
---

# `server-bound-search-production-readiness` research: `timeouts, backpressure, and latency attribution`

This research grounds the decision to treat service-bound search latency and timeout
behavior as a production-readiness concern.

## Findings

### R1. The current default timeout is not compatible with observed service behavior

The live audit launched six same-project service-backed searches in parallel. All timed
out after the default 10 seconds. The service reported same-project search strategy as
`serialized`, which means ordinary agent parallelism can queue work behind itself.

The timeout message was true but not useful. It did not mention service state, active
jobs, same-project serialization, queueing, or the `--timeout` recovery path.

### R2. Raising timeout alone would hide possible regression

The user reported prior benchmarking where RAG was near-instantaneous. The current
server-bound path felt suspiciously slow and required manual index refresh and long job
polling.

The system needs both:

- a realistic user-visible timeout budget, and
- latency SLOs/instrumentation that reveal regressions instead of masking them.

### R3. Service-bound latency needs phase attribution

Without timing breakdowns, a slow or timed-out search cannot be attributed to:

- queue wait,
- same-project serialization,
- embedding,
- Qdrant query,
- sparse search,
- rerank/postprocess,
- response serialization,
- active indexing contention,
- local Qdrant collection size.

Prior Qdrant performance, sparse search latency, async service index, and stress watcher
ADRs should be referenced and extended.

### R4. Timeout diagnostics should read the operational tape

The CLI has access to service status, jobs, and logs, but timeout handling does not
synthesize them. A timeout should explain the likely cause and next action.

For example, a timeout while jobs are running should point to `server jobs --running`.
A timeout behind same-project serialization should say so. A timeout with no active jobs
should point toward performance diagnostics.

### R5. Recommended direction

Adopt a production-readiness contract:

- increase or adapt default service-backed search timeout,
- keep an explicit fail-fast option,
- return timing breakdowns in JSON,
- add request/correlation ids,
- expose queue/backpressure state,
- record last search latency in status/diagnostics,
- benchmark current behavior against prior known-good behavior before declaring the
  server-bound path production-ready.
