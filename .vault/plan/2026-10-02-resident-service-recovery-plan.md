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
body_hash: 'sha256:aff4b23b6d569c1ae7da080491c4174a2e739cb05365bba0e3df3732e291846f'
---

# `resident-service-recovery` plan

## Description

Approved 2026-10-02

The user explicitly authorized fixing all defects discovered in the resident-service incident, continuing investigation, and managing rollout from this checkout. Existing accepted decisions govern these repairs; no new persisted schema, public protocol, or costly architectural choice is proposed. The explicit-reindex and adaptive-watcher decisions govern S01, publication-cost and non-destructive-publication govern S02 and S04, and index-drift detection governs S03 under the later explicit-reindex boundary. Deployment respects live CI resource ownership. S04 includes explicit admitted rebuild jobs for affected roots when their existing proof is incompatible.

S04 live verification also found generic classification of the checkout's sparse-model compatibility refusal and a capability payload hard-coded to the local backend. S06 repairs these service-domain projections under `2026-09-30-sparseencode-adr`, `2026-07-25-storage-conformance-adr`, and `2026-06-13-server-first-default-adr`. The accepted sparse replacement requires explicit rebuild of every populated affected domain; its old sparse vectors must not be reused as replacement-model vectors.

## Steps

- [x] `S01` - Preserve terminal rebuild refusals and accurate watcher status through events, failures, and restart, and reconcile successful verified operator rebuilds; `watcher retry, controller, intake, execution and runtime, jobs.py completion hook, affected watcher and job tests`.
- [x] `S02` - Recover abandoned receipts before certification, preserve unsafe reader fences until explicit rebuild proof commit, and enforce proof before generation publication; `shared publication recovery and checkpoint owner, code/document/vault source entry paths, CPU real-storage recovery and ledger regression tests`.
- [x] `S03` - Stabilize membership identity by pruning unreachable ignore files and verify legitimate nested ignore changes still invalidate proof; `src/vaultspec_rag/indexer/_ignore_specs.py, ignore/policy regression tests`.
- [x] `S05` - Remove stale relevance-feedback anchors before hybrid or dense queries and verify search remains available after point replacement; `src/vaultspec_rag/_store_search.py and store search regression tests`.
- [x] `S06` - Report collection model or geometry incompatibility as terminal explicit-rebuild refusal and report the actual configured backend in service capabilities; `src/vaultspec_rag/store_runtime.py and capabilities.py, storage identity and service capability CPU regressions`.
- [x] `S07` - Require rebuild observation and generation creation after structural scope refusal so an in-flight or resumed older full sweep cannot erase lost scope; `watcher_retry_policy.py rebuild certification and real-ledger watcher rebuild reconciliation regressions`.
- [ ] `S04` - Deploy the current checkout as the resident daemon, repair affected publications through explicit rebuild jobs when required, and verify service health, search, and watcher convergence; `resident service lifecycle, affected root ledgers and admitted jobs, plan verification and final audit`.

## Parallelization

S01 and S02 may run concurrently with disjoint write ownership: the retry worker owns retry, controller settlement, and their tests; the recovery worker owns receipt recovery paths and their tests. The supervisor owns S03 and S05, the operator-job completion hook for S01, shared verification and serialized Git/vault mutations, and S04 service rollout. S04 follows all code repairs.

For the newly discovered S06 and S07, the supervisor owns S06 capability/collection projections and the watcher worker owns S07 rebuild observation cutoffs and their tests. They may run concurrently with disjoint write ownership. S04 rollout follows both; all Git/vault and live service mutations remain serialized under the supervisor.

## Verification

Focused regression and integration checks establish terminal refusal through new events and restart, truthful controller status, abandoned-receipt recovery, and stable membership identity for ignored subtrees while preserving relevant nested ignores. Negative guards receive uninterrupted fail/pass mutation proof. Before each commit, run package lint, format checks, changed-file typing, and affected tests with separately captured exit codes. Final verification exercises the checkout daemon, affected roots, live search, watcher convergence, and lifecycle ownership. No changes are pushed or merged. Completion requires every Step closed and integrated review passing.
