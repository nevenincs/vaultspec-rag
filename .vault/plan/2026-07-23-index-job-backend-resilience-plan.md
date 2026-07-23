---
tags:
  - '#plan'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
tier: L1
related:
  - '[[2026-07-23-index-job-backend-resilience-adr]]'
  - '[[2026-07-23-index-job-backend-resilience-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `index-job-backend-resilience` plan

- [ ] `S01` - Generalise the write-only bounded transient retry into a store-operation retry that any store call can run under, preserving the transient/unrecoverable classification, capped backoff, and durable no-progress budget clamp; `src/vaultspec_rag/_store_writes.py`.
- [ ] `S02` - Run the collection-ensure paths (existence check and payload-index creation) under the bounded retry; `src/vaultspec_rag/store.py`.
- [ ] `S03` - Run the read operations (count, scroll, retrieve) under the bounded retry; `src/vaultspec_rag/store.py`.
- [ ] `S04` - Run the point-delete operations under the bounded retry; `src/vaultspec_rag/store.py`.
- [ ] `S05` - Confirm the unrecoverable storage-exhaustion path still raises on the first attempt for a wrapped read as for a write; `src/vaultspec_rag/_store_writes.py`.
- [ ] `S06` - Add a guard test driving a store operation against a backend that refuses then accepts, asserting bounded-retry survival, and record it failing against the pre-change single-shot path then passing after; `src/vaultspec_rag/tests/`.
- [ ] `S07` - Run the store and indexer test suites plus lint and type checks for the touched modules and record them green with no new suppressions; `src/vaultspec_rag/tests/`.
Extend the bounded transient store retry from the upsert write to connection, ensure, read, and delete operations so a brief backend outage no longer aborts background index jobs.

## Description

This plan executes `2026-07-23-index-job-backend-resilience-adr`: generalise the write-only bounded retry into a store-operation retry and run the store's collection-ensure, read (count/scroll/retrieve), and delete paths under it, keeping the transient-versus-unrecoverable classification, the capped backoff, and the caller-owned durable no-progress budget from `index-backpressure-storage-hygiene`. Grounding, the failure signature, and the observed orphaned-daemon trigger are in `2026-07-23-index-job-backend-resilience-research`. Scope is the client-side operation retry only; server-lifecycle recovery stays with `qdrant-store-resilience`.

## Steps

## Parallelization

`S01` (generalise the helper) is a hard prerequisite for `S02`-`S05`, which wrap the ensure, read, and delete paths and may then land together. `S06` (guard test) asserts the post-change behaviour but takes its failing-direction proof against the pre-change single-shot path. `S07` runs last.

## Verification

- The bounded transient-retry helper accepts any store operation, not only the upsert, and preserves the unrecoverable-raises-immediately rule and the durable no-progress budget clamp.
- Collection-ensure, count, scroll, retrieve, and point-delete store operations run under the bounded retry.
- A guard test drives a store operation against a backend that refuses then accepts the connection and asserts the operation survives via bounded retry; it is observed to fail (immediate hard error) against the pre-change path and pass after, recorded in the execution record per the guard-test obligation.
- The unrecoverable (storage-exhaustion) path still raises on the first attempt for a wrapped read as it does for a write.
- Lint and type checks pass for the touched modules with no new suppressions.
- The plan is complete when every Step is closed.
