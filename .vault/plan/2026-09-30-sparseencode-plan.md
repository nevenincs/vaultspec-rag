---
tags:
  - '#plan'
  - '#sparseencode'
date: '2026-09-30'
tier: L1
related:
  - '[[2026-09-30-sparseencode-adr]]'
  - '[[2026-06-26-storage-schema-contract-adr]]'
  - '[[2026-09-26-gpu-single-owner-adr]]'
  - '[[2026-07-29-encode-batch-adaptivity-adr]]'
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
  - '[[2026-07-25-storage-conformance-adr]]'
modified: '2026-09-30'
body_schema: body-v2
body_hash: 'sha256:8ba9f16de6fa7b8edd1eb2691be806501aae77a52b38d3c5b7218b7144b4e968'
---

<!-- RETIRED: S02 -->

# `sparseencode` plan

## Description

Approved 2026-09-30

Authorization is the user's explicit request for the breaking ModernBERT sparse dependency upgrade, complete removal of the previous authentication work and references, performance optimization, minor version increment, pipeline management and GPT-6.1 Sol subagents.

`2026-09-30-sparseencode-adr` governs the new sparse model, pinned adapter, public acquisition and package version. `2026-06-26-storage-schema-contract-adr` governs model identity and wire-shape compatibility; `2026-09-26-gpu-single-owner-adr` governs device ownership; `2026-07-29-encode-batch-adaptivity-adr` governs batching and memory recovery. The previous GPU-stack ADR continues to govern dense inference and reranking, with its sparse wording reconciled under the new ruling.

## Steps

- [x] `S01` - Migrate sparse inference, provisioning, configuration and public surfaces together to the pinned ModernBERT model, remove obsolete authentication, and release version 0.6.0; `src/vaultspec_rag sparse/model/storage/configuration paths and tests, conftest.py, dev, .github, README.md, docs, assets, .env.example, pyproject.toml, uv.lock and release metadata`.
- [ ] `S03` - Reconcile governing and historical records, verify integrated behavior and measured performance, and resolve final review findings; `.vault governing and historical records, integration tests, performance verification, rolling audit`.

## Parallelization

S01 has two compatible GPT-6.1 Sol assignments that may run concurrently under one supervisor-owned integrated checkpoint. The encoder worker owns `embeddings.py`, new sparse adapter/profile/cache modules, `commands/_provision.py`, model-setup helpers, search lock behavior and encoder/model/storage tests. The surface worker owns configuration modules, remaining credential call sites/tests, README/docs/assets, environment examples, workflows, development gates/harness, package metadata and lockfile. The shared profile/cache interface is supplied by the encoder worker; configuration and warmup integration wait for that interface. Write ownership is disjoint, and no worker commits. The supervisor owns shared gates, GPU borrowing, ledger/plan checkpoints and serialized commits. Combining the migration into one Step ensures each committed revision contains compatible defaults, model code, dependency floors and documentation. S03 follows S01; its record reconciliation may prepare concurrently in existing vault files.

## Verification

Require package lint and format checks, type checks and targeted tests before each Step commit. Exercise the real pinned model on an admitted GPU, including query/document preprocessing, nonzero vocabulary output, batch-versus-single correctness, representation parity and model-identity incompatibility. Verify CPU preparation/conversion happen outside forward locking and preserve input order. Record bounded performance measurements against a reproducible baseline; claim only observed improvements. Prove changed guard assertions can fail and record both directions.

Confirm no removed authentication/model references remain in tracked product code, tests, docs, workflows or vault prose; historical records retain their surrounding meaning after authorized removal. Check model caching/provisioning resolves the same reviewed revision as inference. Check version `0.6.0` consistency, documentation and vault conformance. Completion requires all Steps closed and integrated code review PASS with applicable verification evidence.
