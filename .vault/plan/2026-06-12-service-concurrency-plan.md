---
tags:
  - '#plan'
  - '#service-concurrency'
date: '2026-06-12'
tier: L3
related:
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-06-12-service-concurrency-research]]'
---

# `service-concurrency` `concurrent saturation architecture rework` plan

## Wave `W01` - Adversarial baseline

Build the concurrency benchmark harness (D1) and capture pre-rework saturation baselines on the two-root corpus so every later wave is measured against the same instrument.

### Phase `W01.P01` - Concurrency benchmark harness

Build the saturation benchmark and capture pre-rework baselines.

- [x] `W01.P01.S01` - Create a concurrency benchmark harness driving N parallel searches (same-root, cross-root, vault+code mixed, optional concurrent reindex) against the live service, reporting throughput, p50/p95 latency, and per-phase timings; `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`.
- [x] `W01.P01.S02` - Capture pre-rework baseline numbers on the two-root corpus and persist them in the step record; `.vault/exec/2026-06-12-service-concurrency`.

## Wave `W02` - Retrieval quality core

Fix the critical quality defects: vault chunking (D7), rerank on real content (D3 quality half), contextual embeddings and per-surface instructions (D8), bounded graph nudge (D9).

### Phase `W02.P02` - Vault chunking

Chunk vault documents into heading-aware points while preserving the doc-level search contract.

- [x] `W02.P02.S03` - Chunk vault documents with the heading-aware TextSplitter into one point per chunk carrying doc metadata, ordinal-derived stable IDs, and embed text separated from stored content; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `W02.P02.S04` - Add doc_id payload plumbing, delete-by-document filtering, and index schema version detection that triggers a one-time vault collection rebuild; `src/vaultspec_rag/store.py`.
- [x] `W02.P02.S05` - Group chunk hits per document in vault search with best-chunk scoring and matched-chunk snippets; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W02.P02.S06` - Add unit and GPU integration tests for chunked vault indexing, grouped search, and rebuild-on-schema-bump; `src/vaultspec_rag/tests`.

### Phase `W02.P03` - Rerank and graph scoring

Rerank on token-bounded full content and bound the graph boost.

- [x] `W02.P03.S07` - Rerank with token-bounded full candidate content instead of 200-char snippets and expose reranker max-length configuration; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W02.P03.S08` - Convert the post-rerank multiplicative graph boost into a bounded additive nudge; `src/vaultspec_rag/search/_rerank.py`.
- [ ] `W02.P03.S09` - Update unit and GPU tests for content reranking and the bounded nudge, run the quality harness, and record deltas; `src/vaultspec_rag/tests`.

### Phase `W02.P04` - Contextual embeddings

Contextual headers in embed text and per-surface query instructions.

- [x] `W02.P04.S10` - Prepend contextual headers (path, class, function) to code-chunk embed text while storing raw chunk content; `src/vaultspec_rag/indexer`.
- [x] `W02.P04.S11` - Add per-surface Qwen3 query instructions for vault and codebase searches; `src/vaultspec_rag/embeddings.py`.
- [ ] `W02.P04.S12` - Re-run the quality benchmarks to validate contextual embeddings and record deltas; `src/vaultspec_rag/tests/benchmarks`.

## Wave `W03` - Lock architecture

Remove false sharing: backend-aware per-collection storage locks (D2), gpu_lock narrowed to forward passes with query-embedding cache (D3 concurrency half), sparse conversion hygiene (D10).

### Phase `W03.P05` - Storage lock split

Backend-aware per-collection point-operation locks with a lifecycle lock.

- [x] `W03.P05.S13` - Split the store client lock into a lifecycle lock plus per-collection point-operation locks, backend-aware so server mode runs lock-free; `src/vaultspec_rag/store.py`.
- [x] `W03.P05.S14` - Extend stress tests to assert cross-collection concurrency and same-collection exclusion semantics; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.

### Phase `W03.P06` - GPU lock narrowing and encode hygiene

Forward-pass-only gpu_lock holds, query-embedding LRU, coalesced sparse conversion.

- [x] `W03.P06.S15` - Narrow gpu_lock holds to model forward calls only across the search encode and rerank paths; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W03.P06.S16` - Add a thread-safe LRU query-embedding cache keyed by surface and cleaned query text; `src/vaultspec_rag/embeddings.py`.
- [x] `W03.P06.S17` - Replace the SPLADE densify-and-loop conversion with a single coalesced sparse-tensor pass; `src/vaultspec_rag/embeddings.py`.
- [x] `W03.P06.S18` - Add GPU tests covering narrowed lock holds, cache behavior, and sparse conversion parity; `src/vaultspec_rag/tests`.

## Wave `W04` - Service plumbing

Async-safe MCP transport (D4), dedicated capacity limiters (D5), event-loop hygiene (D6), and concurrency telemetry (D11).

### Phase `W04.P07` - Async plumbing and limiters

Thread-dispatched MCP transport, capacity limiters, loop hygiene, telemetry.

- [x] `W04.P07.S19` - Dispatch MCP tool daemon calls off the event loop preserving existing timeouts; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `W04.P07.S20` - Introduce env-tunable search and index capacity limiters replacing shared default thread-pool usage; `src/vaultspec_rag/server`.
- [x] `W04.P07.S21` - Move the cold ensure-watcher peek and log reads off the event loop; `src/vaultspec_rag/server/_watcher.py`.
- [x] `W04.P07.S22` - Surface limiter depth and lock-wait telemetry through the existing bounded metrics plumbing; `src/vaultspec_rag/server/_state.py`.

## Wave `W05` - Adversarial validation gate

Rebuild corpora, run the full saturation matrix against the W01 baseline, verify quality parity, and close with persona verification.

### Phase `W05.P08` - Saturation validation

Adversarial matrix vs baseline, quality parity, persona verification.

- [ ] `W05.P08.S23` - Rebuild both corpora under the new schema and run the adversarial saturation matrix against the W01 baseline, recording results; `.vault/exec/2026-06-12-service-concurrency`.
- [ ] `W05.P08.S24` - Run the quality harness comparison and manual persona CLI verification in human and JSON modes; `src/vaultspec_rag/tests/benchmarks`.
- [ ] `W05.P08.S25` - Record the execution summary and prepare the review handoff; `.vault/exec/2026-06-12-service-concurrency`.

## Description

Executes the service-concurrency ADR: rework the resident service and search backend
so they serve multiple agents, concurrent repo roots, and saturated call loads, and
fix the retrieval-quality defects found in the same review. The plan is
benchmark-bracketed: W01 builds the adversarial saturation harness and freezes the
baseline; W02 fixes quality (vault chunking, content reranking, contextual
embeddings, bounded graph nudge) because quality changes move benchmark numbers and
must land before lock-surgery measurements; W03 removes lock false-sharing
(per-collection backend-aware storage locks, forward-pass-only gpu_lock holds); W04
fixes the async plumbing (MCP transport, capacity limiters, loop hygiene, telemetry);
W05 is the adversarial acceptance gate against the W01 baseline. Authorising
documents are carried in this plan's frontmatter `related:` chain.

## Steps

Step rows live in the Wave blocks above (`W01` - `W05`).

## Parallelization

Waves are sequential: W01's baseline must precede any behavior change; W02 must
precede W03 measurements (quality changes alter request cost); W05 requires all prior
waves. Within W02, P02 (vault chunking) and P03 (rerank/graph) touch
`search/_searcher.py` in adjacent regions and run sequentially; P04 may interleave
after P02 lands. Within W03, P05 (`store.py`) and P06 (searcher/embeddings) are
disjoint and could parallelize, but sequential execution is preferred to keep GPU
test runs serialized on the single device. W04 steps are mutually independent except
S22 (telemetry), which consumes S20's limiters. All work shares one branch with the
in-flight operability feature: edits to `server/_routes.py` and `watcher.py` stay
minimal and additive.

## Verification

- Every wave: full unit suite (`uv run vaultspec-rag test`) green; ruff/ty/complexity
  pre-commit hooks pass on touched files; GPU integration tests run locally (real
  GPU, real Qdrant - no mocks or skips).
- W01/W05: the saturation matrix (same-root, cross-root, mixed, search-during-index)
  reports throughput and p50/p95 against the 6.3 GB two-root corpus; W05 must show
  improved saturated throughput, no deadlock or starvation, and
  `gpu_queue_wait_seconds`/`qdrant_seconds` attribution consistent with the lock
  changes.
- W02: quality harness (`benchmark`/`quality`) deltas recorded per phase; vault
  chunking proves long-document retrieval past the old 8000-char horizon; reranker
  receives token-bounded full content.
- W05: manual persona verification of `vaultspec-rag search` in human and JSON modes
  per the CLI operability rule; step records and a phase summary persisted under
  `.vault/exec/2026-06-12-service-concurrency/`.
