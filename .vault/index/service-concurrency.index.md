---
generated: true
tags:
  - '#index'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
related:
  - '[[2026-06-12-service-concurrency-W01-P01-S01]]'
  - '[[2026-06-12-service-concurrency-W01-P01-S02]]'
  - '[[2026-06-12-service-concurrency-W02-P02-S03]]'
  - '[[2026-06-12-service-concurrency-W02-P02-S04]]'
  - '[[2026-06-12-service-concurrency-W02-P02-S05]]'
  - '[[2026-06-12-service-concurrency-W02-P02-S06]]'
  - '[[2026-06-12-service-concurrency-W02-P03-S07]]'
  - '[[2026-06-12-service-concurrency-W02-P03-S08]]'
  - '[[2026-06-12-service-concurrency-W02-P03-S09]]'
  - '[[2026-06-12-service-concurrency-W02-P04-S10]]'
  - '[[2026-06-12-service-concurrency-W02-P04-S11]]'
  - '[[2026-06-12-service-concurrency-W02-P04-S12]]'
  - '[[2026-06-12-service-concurrency-W03-P05-S13]]'
  - '[[2026-06-12-service-concurrency-W03-P05-S14]]'
  - '[[2026-06-12-service-concurrency-W03-P06-S15]]'
  - '[[2026-06-12-service-concurrency-W03-P06-S16]]'
  - '[[2026-06-12-service-concurrency-W03-P06-S17]]'
  - '[[2026-06-12-service-concurrency-W03-P06-S18]]'
  - '[[2026-06-12-service-concurrency-W04-P07-S19]]'
  - '[[2026-06-12-service-concurrency-W04-P07-S20]]'
  - '[[2026-06-12-service-concurrency-W04-P07-S21]]'
  - '[[2026-06-12-service-concurrency-W04-P07-S22]]'
  - '[[2026-06-12-service-concurrency-W05-P08-S23]]'
  - '[[2026-06-12-service-concurrency-W05-P08-S24]]'
  - '[[2026-06-12-service-concurrency-W05-P08-S25]]'
  - '[[2026-06-12-service-concurrency-W05-P08-summary]]'
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-06-12-service-concurrency-audit]]'
  - '[[2026-06-12-service-concurrency-plan]]'
  - '[[2026-06-12-service-concurrency-research]]'
---

# `service-concurrency` feature index

Auto-generated index of all documents tagged with `#service-concurrency`.

## Documents

### adr

- `2026-06-12-service-concurrency-adr` - `service-concurrency` adr: `concurrent saturation architecture rework` | (**status:** `accepted`)

### audit

- `2026-06-12-service-concurrency-audit` - `service-concurrency` Code Review

### exec

- `2026-06-12-service-concurrency-W01-P01-S01` - Create a concurrency benchmark harness driving N parallel searches (same-root, cross-root, vault+code mixed, optional concurrent reindex) against the live service, reporting throughput, p50/p95 latency, and per-phase timings
- `2026-06-12-service-concurrency-W01-P01-S02` - Capture pre-rework baseline numbers on the two-root corpus and persist them in the step record
- `2026-06-12-service-concurrency-W02-P02-S03` - Chunk vault documents with the heading-aware TextSplitter into one point per chunk carrying doc metadata, ordinal-derived stable IDs, and embed text separated from stored content
- `2026-06-12-service-concurrency-W02-P02-S04` - Add doc_id payload plumbing, delete-by-document filtering, and index schema version detection that triggers a one-time vault collection rebuild
- `2026-06-12-service-concurrency-W02-P02-S05` - Group chunk hits per document in vault search with best-chunk scoring and matched-chunk snippets
- `2026-06-12-service-concurrency-W02-P02-S06` - Add unit and GPU integration tests for chunked vault indexing, grouped search, and rebuild-on-schema-bump
- `2026-06-12-service-concurrency-W02-P03-S07` - Rerank with token-bounded full candidate content instead of 200-char snippets and expose reranker max-length configuration
- `2026-06-12-service-concurrency-W02-P03-S08` - Convert the post-rerank multiplicative graph boost into a bounded additive nudge
- `2026-06-12-service-concurrency-W02-P03-S09` - Update unit and GPU tests for content reranking and the bounded nudge, run the quality harness, and record deltas
- `2026-06-12-service-concurrency-W02-P04-S10` - Prepend contextual headers (path, class, function) to code-chunk embed text while storing raw chunk content
- `2026-06-12-service-concurrency-W02-P04-S11` - Add per-surface Qwen3 query instructions for vault and codebase searches
- `2026-06-12-service-concurrency-W02-P04-S12` - Re-run the quality benchmarks to validate contextual embeddings and record deltas
- `2026-06-12-service-concurrency-W03-P05-S13` - Split the store client lock into a lifecycle lock plus per-collection point-operation locks, backend-aware so server mode runs lock-free
- `2026-06-12-service-concurrency-W03-P05-S14` - Extend stress tests to assert cross-collection concurrency and same-collection exclusion semantics
- `2026-06-12-service-concurrency-W03-P06-S15` - Narrow gpu_lock holds to model forward calls only across the search encode and rerank paths
- `2026-06-12-service-concurrency-W03-P06-S16` - Add a thread-safe LRU query-embedding cache keyed by surface and cleaned query text
- `2026-06-12-service-concurrency-W03-P06-S17` - Replace the SPLADE densify-and-loop conversion with a single coalesced sparse-tensor pass
- `2026-06-12-service-concurrency-W03-P06-S18` - Add GPU tests covering narrowed lock holds, cache behavior, and sparse conversion parity
- `2026-06-12-service-concurrency-W04-P07-S19` - Dispatch MCP tool daemon calls off the event loop preserving existing timeouts
- `2026-06-12-service-concurrency-W04-P07-S20` - Introduce env-tunable search and index capacity limiters replacing shared default thread-pool usage
- `2026-06-12-service-concurrency-W04-P07-S21` - Move the cold ensure-watcher peek and log reads off the event loop
- `2026-06-12-service-concurrency-W04-P07-S22` - Surface limiter depth and lock-wait telemetry through the existing bounded metrics plumbing
- `2026-06-12-service-concurrency-W05-P08-S23` - Rebuild both corpora under the new schema and run the adversarial saturation matrix against the W01 baseline, recording results
- `2026-06-12-service-concurrency-W05-P08-S24` - Run the quality harness comparison and manual persona CLI verification in human and JSON modes
- `2026-06-12-service-concurrency-W05-P08-S25` - Record the execution summary and prepare the review handoff
- `2026-06-12-service-concurrency-W05-P08-summary` - `service-concurrency` `W05.P08` summary

### plan

- `2026-06-12-service-concurrency-plan` - `service-concurrency` `concurrent saturation architecture rework` plan

### research

- `2026-06-12-service-concurrency-research` - `service-concurrency` research: `concurrent service saturation architecture`
