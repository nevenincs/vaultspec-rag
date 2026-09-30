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
body_hash: 'sha256:f5373038ec588f12f94fe5daa776325aa6b81222fd1dd8621dd319b65c7152d2'
---

# `pipeline-performance` plan

## Description

Approved 2026-09-30

The user's continuation explicitly authorizes rigorous py-spy and GPU analysis, further benchmarking, and performance/GPU-usage improvements across dense encoding, sparse encoding and code chunking, continuing with GPT-6.1 Sol agents. S01 establishes repeatable measurement and reviewed native-tool pins. S02 checkpoints the measured AST change independently of GPU availability. S03 measures the dense/sparse paths and sustained device-wide energy, selects compatible tuning, and verifies unchanged encoder semantics. S04 verifies and independently reviews the integrated result. The user clarified that indexing time and GPU energy use guide optimization; peak memory remains a supporting measurement.

Accepted sparseencode and batch-adaptivity decisions govern representation, pinned upstream sparse semantics, canonical dense library encoding, token-budget planning and bucket-local OOM retry. GPU-single-owner and GPU-pipeline decisions govern admitted borrowing, exactly one dedicated GPU consumer, CPU-only spawned workers and forward locking. Large-index-resilience governs bounded retention, durable storage/checkpoint ordering and live-data preservation. Profiling and compatible tuning fit this authority without a new costly commitment. Default backend/precision changes, replacement pooling, reranker eviction or compatibility changes require decision coverage based on measured evidence before implementation.

Semantic discovery was attempted for code and decisions but this worktree's sources remain missing/unverifiable; empty results were not treated as absence. Full ADR listing and specific code reads provided the fallback grounding.

## Steps

- [x] `S01` - Add a reproducible CPU and CUDA profiling harness with verified native profiler provenance and baseline manifests; `dev profiling tools and focused harness tests, .vault research and enrollment`.
- [x] `S02` - Implement the measured AST decoding improvement and verify exact chunk behavior and paired CPU timing; `src/vaultspec_rag/indexer/_ast_chunker.py and focused chunking tests, .vault measured research`.
- [x] `S03` - Measure admitted dense and sparse CUDA workloads and sustained energy, implement supported tuning, and verify paired performance and encoder parity; `dev profiling tools and focused tests, src/vaultspec_rag encoder paths and tests, .vault GPU research`.
- [x] `S04` - Complete integrated verification and independent review, recording measured gains and unresolved performance opportunities; `.vault audit and execution ledger, affected documentation and profiling artifact summaries, test substitution policy declaration`.

## Parallelization

S01 profiling-tool implementation and supervisor-owned vault enrollment may proceed concurrently. S02 owns AST chunking. S03 may delegate energy-harness implementation independently of supervisor-owned admitted GPU runs; encoder edits follow the measured common baseline. Source/test ownership stays disjoint. The supervisor owns all GPU/profiler runs, native-tool provenance verification, shared gates, paired measurements, ledger/plan updates and commits. Workers do not allocate CUDA, launch native profilers, operate services or mutate shared records unless explicitly assigned. S04 uses one independent reviewer and reuses applicable verification evidence.

## Verification

Capture source/corpus hashes, versions, model revision, dtype/attention, real token/padding lengths, caps and environment. Keep CPU stack sampling and instrumented CUDA traces separate from unprofiled synchronized performance runs. Confirm exported traces actually contain CUDA kernels before claiming device attribution. Report live allocation, reserved allocator memory and device-wide occupancy separately. Profile code chunking, dense/sparse inference and their combined production order; use representative short, long, mixed and token-dense content.

For energy, use sustained identical combined dense/sparse workloads and alternate configuration order. Integrate finite nonnegative one-second NVML power samples over their measured span, disclose coverage/gaps and desktop/background contributions, and withhold per-item estimates when coverage is insufficient. Encoder throughput and device-wide energy are proxies for indexing; an end-to-end indexing claim requires the production producer/store path.

Compare unchanged baseline and candidate with warmups, alternating repeated runs and individual observations. Validate chunk text/spans/metadata/identity/order and model vectors/nonzero coordinates/scores, not just timing. Exercise realistic sparse item caps and OOM/progress behavior. Never claim throughput, memory, backend or quality gains beyond the evidence. No per-bucket cache flushing, second GPU consumer or live-index rebuild is introduced.

Run relevant lint/format/type/tests and document gates per cohesive checkpoint; mutation-prove any changed guard. Verify native executables against committed reviewed SHA256 pins before execution. Maintain bounded profiler duration/cleanup and authenticated borrowing that resumes the resident service. Completion requires all Steps checked, clean feature conformance and integrated review PASS.
