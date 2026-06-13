---
tags:
  - '#adr'
  - '#server-bound-search-production-readiness'
date: '2026-06-11'
modified: '2026-06-11'
related:
  - '[[2026-06-11-server-bound-search-production-readiness-research]]'
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-06-05-qdrant-performance-adr]]'
  - '[[2026-06-07-sparse-search-latency-adr]]'
  - '[[2026-06-05-service-stress-watcher-adr]]'
  - '[[2026-06-02-index-gpu-pipeline-adr]]'
---

# `server-bound-search-production-readiness` adr: `timeouts, backpressure, and latency attribution` | (**status:** `accepted`)

## Problem Statement

The current server-bound search path is not production-credible under observed agent
usage. Parallel same-project searches timed out at the default 10-second budget, and the
error did not explain service busy state, queueing, active jobs, or next actions.

The user also reported suspected performance regression from earlier near-instant RAG
behavior.

## Considerations

- The service reports same-project search as serialized.
- Local Qdrant has exclusive process constraints.
- Indexing and search can contend for GPU, Qdrant, and writer locks.
- Raising the timeout can improve usability but can also hide regression.
- Prior performance ADRs address Qdrant, sparse search, and indexing, but not full
  service-bound latency attribution.

## Constraints

- Timeout policy must support both interactive users and fail-fast scripts.
- Instrumentation must be low overhead.
- Backpressure behavior must respect local Qdrant ownership and single GPU constraints.
- Performance claims must be backed by measurements, not impressions.

## Implementation

Adopt a production-readiness contract for service-backed search:

- increase or adapt the default timeout for service-bound search,
- keep an explicit fail-fast option,
- report service busy, queue, and active job state on timeout,
- add request timing breakdowns for queue wait, embedding, Qdrant query, rerank,
  postprocess, and response rendering,
- add request/correlation ids,
- expose last search latency and queue state in diagnostics,
- run regression benchmarks against prior known-good behavior.

## Rationale

The CLI must not fail with generic timeouts when it can inspect the service it is calling.
Operators need to know whether to wait, retry, stop work, or investigate a regression.

## Consequences

Search code, service routes, CLI HTTP client behavior, jobs/status integration, and tests
will need coordinated changes. The work may expose deeper Qdrant local-mode limitations.

## Codification candidates

- **Rule slug:** `timeouts-report-operational-state`.
  **Rule:** CLI timeouts against the resident service must report service state, active
  work, and a concrete next action.

- **Rule slug:** `latency-claims-need-phase-attribution`.
  **Rule:** Production-readiness latency work must attribute time to queue, embedding,
  vector search, rerank, and response phases before declaring improvement.
