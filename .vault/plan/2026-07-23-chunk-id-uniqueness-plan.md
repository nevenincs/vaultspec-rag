---
tags:
  - '#plan'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
tier: L1
related:
  - '[[2026-07-23-chunk-id-uniqueness-adr]]'
  - '[[2026-07-23-chunk-id-uniqueness-research]]'
---

# `chunk-id-uniqueness` plan

- [x] `S01` - Add the zero-based per-file emit ordinal as a leading discriminator to the AST-path chunk identifier so byte-identical slices of one line cannot collide; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `S02` - Add the same per-file emit ordinal discriminator to the text-splitter fallback chunk identifier; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `S03` - Add a guard test that chunks a repeated-content over-budget line through the real chunker, asserts unique identifiers and commit-unit acceptance, and record it failing against the pre-fix construction then passing after; `src/vaultspec_rag/tests/test_chunk_worker_parity.py`.
- [x] `S04` - Run the indexer test suite plus lint and type checks for the touched modules and record them green with no new suppressions; `src/vaultspec_rag/tests/`.
  Make code-chunk identifiers unique by construction so a repeated-content long line can no longer collide two chunks and fail an entire code-index update.

## Description

This plan executes `2026-07-23-chunk-id-uniqueness-adr`: every code-chunk identifier gains the chunk's zero-based per-file emit ordinal as a leading discriminator, adopting the convention the preprocess-unit path already uses. Two non-preprocess construction sites in the chunk worker - the AST path and the text-splitter fallback - are corrected, a guard test proves the collision is gone and that it binds (fails against the pre-fix construction), and the touched modules pass lint and type checks. Grounding evidence and the reproduction are in `2026-07-23-chunk-id-uniqueness-research`.

## Steps

## Parallelization

`S01` and `S02` touch the same module at two adjacent construction sites and should land together in one edit pass. `S03` depends on both corrections being present to assert the fixed behaviour, but its failing-direction proof is taken against the pre-fix code before `S01`/`S02` are applied. `S04` runs last.

## Verification

- A guard test drives a single repeated-content line exceeding the chunk budget through the real chunker and asserts every emitted identifier is unique and that a commit unit built from them is accepted.
- That guard test is observed to fail against the pre-fix identifier construction (for the intended reason - a duplicate identifier) and pass after, recorded in the execution record per the guard-test obligation.
- The three chunk-construction paths emit identifiers carrying a per-file emit ordinal.
- Lint and type checks pass for the touched modules with no new suppressions.
- The plan is complete when every Step is closed.
