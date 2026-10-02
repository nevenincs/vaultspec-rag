---
tags:
  - '#plan'
  - '#pipeline-performance'
date: '2026-09-30'
tier: L1
related:
  - '[[2026-09-30-sparseencode-adr]]'
  - '[[2026-07-29-encode-batch-adaptivity-adr]]'
  - '[[2026-09-26-gpu-single-owner-adr]]'
  - '[[2026-06-02-index-gpu-pipeline-adr]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
modified: '2026-09-30'
body_schema: body-v2
body_hash: 'sha256:d4623b23887c8e6e29c0f3698284a3086d3dd6ee34b8b9495976bb28086639ce'
---

# `pipeline-performance` plan

## Description

Approved 2026-09-30

The user's continuation explicitly authorizes rigorous py-spy and GPU analysis, further benchmarking, and performance/GPU-usage improvements across dense encoding, sparse encoding and code chunking, continuing with GPT-6.1 Sol agents. S01 establishes repeatable measurement and reviewed native-tool pins. S02 selects changes from measured bottlenecks and compares them with unchanged baseline semantics. S03 verifies and independently reviews the integrated result.

Accepted sparseencode and batch-adaptivity decisions govern representation, pinned upstream sparse semantics, canonical dense library encoding, token-budget planning and bucket-local OOM retry. GPU-single-owner and GPU-pipeline decisions govern admitted borrowing, exactly one dedicated GPU consumer, CPU-only spawned workers and forward locking. Large-index-resilience governs bounded retention, durable storage/checkpoint ordering and live-data preservation. Profiling and compatible tuning fit this authority without a new costly commitment. Default backend/precision changes, replacement pooling, reranker eviction or compatibility changes require decision coverage based on measured evidence before implementation.

Semantic discovery was attempted for code and decisions but this worktree's sources remain missing/unverifiable; empty results were not treated as absence. Full ADR listing and specific code reads provided the fallback grounding.

## Steps

- [x] `S01` - Add a reproducible CPU and CUDA profiling harness with verified native profiler provenance and baseline manifests; `dev profiling tools and focused harness tests, .vault research and enrollment`.
- [ ] `S02` - Measure current workloads, implement supported encoder and chunking improvements, and compare paired performance with behavior parity; `src/vaultspec_rag embeddings and chunking paths and focused tests, dev profiling tools, .vault measured research`.
- [ ] `S03` - Complete integrated verification and independent review, recording measured gains and unresolved performance opportunities; `.vault audit and execution ledger, affected user documentation and profiling artifact summaries`.

## Parallelization

S01 profiling-tool implementation and supervisor-owned vault enrollment may proceed concurrently. S02 may assign encoder and AST-chunking edits concurrently only after a common measured baseline identifies each bottleneck; their source and test ownership are disjoint. The supervisor owns all GPU/profiler runs, native-tool provenance verification, shared gates, paired measurements, ledger/plan updates and commits. Workers do not allocate CUDA, launch native profilers, operate services or mutate shared records unless explicitly assigned. S03 uses one independent reviewer and reuses applicable verification evidence.

## Verification

Capture source/corpus hashes, versions, model revision, dtype/attention, real token/padding lengths, caps and environment. Keep CPU stack sampling and instrumented CUDA traces separate from unprofiled synchronized performance runs. Confirm exported traces actually contain CUDA kernels before claiming device attribution. Report live allocation, reserved allocator memory and device-wide occupancy separately. Profile code chunking, dense/sparse inference and their combined production order; use representative short, long, mixed and token-dense content.

Compare unchanged baseline and candidate with warmups, alternating repeated runs and individual observations. Validate chunk text/spans/metadata/identity/order and model vectors/nonzero coordinates/scores, not just timing. Exercise realistic sparse item caps and OOM/progress behavior. Never claim throughput, memory, backend or quality gains beyond the evidence. No per-bucket cache flushing, second GPU consumer or live-index rebuild is introduced.

Run relevant lint/format/type/tests and document gates per cohesive checkpoint; mutation-prove any changed guard. Verify native executables against committed reviewed SHA256 pins before execution. Maintain bounded profiler duration/cleanup and authenticated borrowing that resumes the resident service. Completion requires all Steps checked, clean feature conformance and integrated review PASS.
