---
generated: true
tags:
  - '#index'
  - '#index-job-backend-resilience'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:d3b5314862066d007de9d7c8d82ced7c5e9bbb5c1c38d9264df13c66dbb41d0d'
related:
  - '[[2026-07-23-index-job-backend-resilience-S01]]'
  - '[[2026-07-23-index-job-backend-resilience-S02]]'
  - '[[2026-07-23-index-job-backend-resilience-S03]]'
  - '[[2026-07-23-index-job-backend-resilience-S04]]'
  - '[[2026-07-23-index-job-backend-resilience-S05]]'
  - '[[2026-07-23-index-job-backend-resilience-S06]]'
  - '[[2026-07-23-index-job-backend-resilience-S07]]'
  - '[[2026-07-23-index-job-backend-resilience-adr]]'
  - '[[2026-07-23-index-job-backend-resilience-plan]]'
  - '[[2026-07-23-index-job-backend-resilience-research]]'
---

# `index-job-backend-resilience` feature index

Auto-generated index of all documents tagged with `#index-job-backend-resilience`.

## Documents

### adr

- `2026-07-23-index-job-backend-resilience-adr` - `index-job-backend-resilience` adr: `bounded transient retry across all store operations` | (**status:** `accepted`)

### exec

- `2026-07-23-index-job-backend-resilience-S01` - Generalise the write-only bounded transient retry into a store-operation retry that any store call can run under, preserving the transient/unrecoverable classification, capped backoff, and durable no-progress budget clamp
- `2026-07-23-index-job-backend-resilience-S02` - Run the collection-ensure paths (existence check and payload-index creation) under the bounded retry
- `2026-07-23-index-job-backend-resilience-S03` - Run the read operations (count, scroll, retrieve) under the bounded retry
- `2026-07-23-index-job-backend-resilience-S04` - Run the point-delete operations under the bounded retry
- `2026-07-23-index-job-backend-resilience-S05` - Confirm the unrecoverable storage-exhaustion path still raises on the first attempt for a wrapped read as for a write
- `2026-07-23-index-job-backend-resilience-S06` - Add a guard test driving a store operation against a backend that refuses then accepts, asserting bounded-retry survival, and record it failing against the pre-change single-shot path then passing after
- `2026-07-23-index-job-backend-resilience-S07` - Run the store and indexer test suites plus lint and type checks for the touched modules and record them green with no new suppressions

### plan

- `2026-07-23-index-job-backend-resilience-plan` - `index-job-backend-resilience` plan

### research

- `2026-07-23-index-job-backend-resilience-research` - `index-job-backend-resilience` research: `connect and read paths bypass the bounded store retry`
