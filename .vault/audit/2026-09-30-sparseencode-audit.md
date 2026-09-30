---
tags:
  - '#audit'
  - '#sparseencode'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:35da92f59183939a33f366cc2933ac6d0e66d17abe9c27667489e7599d4dab1c'
related:
  - "[[2026-09-30-sparseencode-plan]]"
  - "[[2026-09-30-sparseencode-adr]]"
---

# `sparseencode` audit: `Integrated breaking sparse upgrade review`

## Scope

The review covers the integrated S01 implementation and S03 reconciliation under `2026-09-30-sparseencode-plan`, from base `3311ccdfb4bb5c3d1ef825f799c36f788a9d0c31` through the supervised working tree and its Step checkpoints. The reviewer is a GPT-6.1 Sol subagent; the supervisor owns shared gates, GPU borrowing and commits. Governing decisions are the accepted sparseencode ruling, storage identity/conformance, single GPU ownership and batch adaptivity. Reviewed interfaces include configuration, pinned acquisition/cache readiness, inference locks and ordering, model mismatch refusal/rebuild recovery, release metadata, CI, operator migration guidance and authorized historical reference removal.

Review status: PENDING final checkpoint and verdict. Implementation and records are stable; no unresolved code finding remains. Verification details and resolved findings will be appended below.

## Findings

### rebuild-recovery | high | Sparse mismatch refusal must reach existing rebuild recovery

Resolved before checkpoint. A newly independent error type would bypass vault/document indexer catches for the established storage compatibility superclass. `StorageModelError` now subclasses `StorageGeometryError`; the distinct sparse mismatch verdict still refuses ordinary reads/writes, and explicit rebuild can recover through existing paths. The reviewer traced vault, document and code rebuild routing, including code generation publication. Real local-store tests exercise typed refusal, administrative recovery, empty recreation and the conforming replacement stamp; they do not claim to invoke every full indexer end to end. Evidence: the 295-test supervisor selection includes `test_storage_identity.py`, and the refusal guard's mutation failed with DID NOT RAISE before its restored pass.

### cache-readiness | high | Sparse readiness must require the reviewed complete revision

Resolved before checkpoint. The old readiness probe accepted an unpinned config-only cache entry while inference required the reviewed remote implementation and complete weights. Readiness, provisioning, warmup and test setup now share the offline full-snapshot probe; the sparse default resolves its pinned revision and required code/tokenizer/safetensors files. Readiness remains torch-free. Focused readiness tests, a fresh subprocess import check and the supervisor selection passed. Cache completeness and safetensors/pin guards were mutation-proved and restored.

### maintained-surfaces | low | Release and governing prose must match the implemented adapter

Resolved before checkpoint. The batching ADR now permits the scoped adapter that delegates pinned upstream semantics; dense library encoding remains authoritative. Operability no longer promises an unimplemented custom failure envelope. Configuration fallbacks, final-vector top-k wording, readiness/cache descriptions and guard-proof prose match code. Two empty workflow environment mappings left by acquisition removal were removed; actionlint and nine CI hardware guards passed.

## Recommendations

Retain float32/SDPA at the measured revision. Rebuild sparse indexes explicitly after installing version 0.6.0. Re-review upstream Python implementation and representation compatibility before changing the pinned revision. The benchmark establishes only the measured mixed-length CUDA batching improvement; it does not establish Apple MPS support, retrieval-quality equivalence with the retired model, or lower peak memory.
