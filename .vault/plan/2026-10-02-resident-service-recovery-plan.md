---
tags:
  - '#plan'
  - '#resident-service-recovery'
date: '2026-10-02'
tier: L1
related:
  - '[[2026-09-07-explicit-reindex-authority-adr]]'
  - '[[2026-09-08-adaptive-watcher-control-adr]]'
  - '[[2026-09-08-incremental-publication-cost-adr]]'
  - '[[2026-07-25-non-destructive-index-publication-adr]]'
  - '[[2026-07-13-index-drift-hardening-adr]]'
modified: '2026-10-02'
body_schema: body-v2
body_hash: 'sha256:e9e33ccc2e0816adb53abfeefe3d2884ce2108cfcca3772021c4761c4e3cb6e8'
---

# `resident-service-recovery` plan

## Description

Approved 2026-10-02

The user explicitly authorized fixing all defects discovered in the resident-service incident, continuing investigation, and managing rollout from this checkout. Existing accepted decisions govern these repairs; no new persisted schema, public protocol, or costly architectural choice is proposed. The explicit-reindex and adaptive-watcher decisions govern S01, publication-cost and non-destructive-publication govern S02 and S04, and index-drift detection governs S03 under the later explicit-reindex boundary. Deployment respects live CI resource ownership. S04 includes explicit admitted rebuild jobs for affected roots when their existing proof is incompatible.

## Steps

- [ ] `S01` - Preserve terminal rebuild refusals and accurate watcher controller status across new events, failed attempts, and restart; `src/vaultspec_rag/watcher_retry_policy.py, watcher_execution.py, watcher_controller.py, affected watcher tests`.
- [ ] `S02` - Recover abandoned publication receipts before certification and validate bounded replay or rollback across source adapters; `src/vaultspec_rag/indexer publication recovery, vault incremental/checkpoint paths, publication integration tests`.
- [x] `S03` - Stabilize membership identity by pruning unreachable ignore files and verify legitimate nested ignore changes still invalidate proof; `src/vaultspec_rag/indexer/_ignore_specs.py, ignore/policy regression tests`.
- [ ] `S04` - Deploy the current checkout as the resident daemon, repair affected publications through explicit rebuild jobs when required, and verify service health, search, and watcher convergence; `resident service lifecycle, affected root ledgers and admitted jobs, plan verification and final audit`.

## Parallelization

S01 and S02 may run concurrently with disjoint ownership: the retry worker owns watcher retry, controller settlement, and corresponding tests; the recovery worker owns publication recovery and corresponding tests. The supervisor owns S03 ignore collection, shared verification and serialized git/vault mutations, and S04 service operations. S04 follows S01-S03.

## Verification

Focused regression and integration checks establish terminal refusal through new events and restart, truthful controller status, abandoned-receipt recovery, and stable membership identity for ignored subtrees while preserving relevant nested ignores. Negative guards receive uninterrupted fail/pass mutation proof. Before each commit, run package lint, format checks, changed-file typing, and affected tests with separately captured exit codes. Final verification exercises the checkout daemon, affected roots, live search, watcher convergence, and lifecycle ownership. No changes are pushed or merged. Completion requires every Step closed and integrated review passing.
