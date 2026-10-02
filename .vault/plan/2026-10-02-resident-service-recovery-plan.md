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
  - '[[2026-09-30-sparseencode-adr]]'
  - '[[2026-07-25-storage-conformance-adr]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-05-30-service-lifecycle-adr]]'
  - '[[2026-05-31-service-token-identity-adr]]'
  - '[[2026-07-23-service-orphan-reaping-adr]]'
  - '[[2026-07-27-cli-service-operability-hardening-adr]]'
  - '[[2026-06-24-service-hardware-singleton-adr]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
  - '[[2026-07-25-index-resume-drift-race-adr]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-adr]]'
  - '[[2026-07-21-code-document-index-boundary-adr]]'
modified: '2026-10-02'
body_schema: body-v2
body_hash: 'sha256:89455318cd4296d0ddeecd186605962db09cb38755696fea7d68db00ac0b8c53'
---

# `resident-service-recovery` plan

## Description

Approved 2026-10-02

The user explicitly authorized fixing all defects discovered in the resident-service incident, continuing investigation, and managing rollout from this checkout. The explicit-reindex and adaptive-watcher decisions govern S01, publication-cost and non-destructive-publication govern S02 and S04, and index-drift detection governs S03 under the later explicit-reindex boundary. Deployment respects live CI resource ownership. S04 includes explicit admitted rebuild jobs for affected roots when their existing proof is incompatible.

S04 live verification also found generic classification of the checkout's sparse-model compatibility refusal and a capability payload hard-coded to the local backend. S06 repairs these service-domain projections under `2026-09-30-sparseencode-adr`, `2026-07-25-storage-conformance-adr`, and `2026-06-13-server-first-default-adr`. The accepted sparse replacement requires explicit rebuild of every populated affected domain; its old sparse vectors must not be reused as replacement-model vectors.

Further live lifecycle testing found an explicit-port stop reporting absence while its recorded startup daemon still held Qdrant resources. S08 follows the accepted lifecycle, hardware singleton, token identity, orphan reaping, and CLI operability boundaries. Independent review confirmed the deployed CI resident reconciler could restart a held service during a different dependent native grant and mistake a port-absent warming daemon for absence. S09 repairs that implementation on the isolated ci-fleet branch fix/resident-start-admission. Its accepted `2026-10-01-slot-admission-resident-service-adr` was amended on 2026-10-02, under the user's advance authorization to fix and roll out every incident defect, to add a distinct protected operator presence probe task. The task reuses RAG's existing status exit contract; no new RAG protocol or persisted resident-record schema is introduced. Authoritative readiness belongs to the next dependent attempt, including prepared waiters and handoff, and unknown observation blocks admission. Existing tolerance for an external restart during active CI remains under the runtime resource floor.

An owned operator maintenance hold pauses new CI grants without cancelling active work; timed cleanup restores enabled action tasks and removes only this operation's hold. The supervisor owns all live operations and serialized Git/vault mutations.

The first live linked code retry exposed S10: checkpoint selection removes already committed file segments before a consumer validates contiguous file/ordinal framing, so a legitimate compatible resume is rejected as a malformed stream. This is an in-scope correction under the existing publication-cost and non-destructive-publication decisions, retaining original durable segment identities and strong rejection of truly malformed producers. Semantic code discovery was attempted but the affected index was unavailable during replacement; exact traceback and source ownership ground the fallback. No schema or public protocol change is proposed. A timed-out later retry did create a linked child; reconciliation must recover its actual identity before submitting more work.

S11 follows a live ingest code rebuild that confirmed every source file, bound its replacement collection, then failed during payload-only route reconciliation against the old-model document origin. The accepted sparse replacement and storage conformance rules still prohibit reading or reusing incompatible vectors; routing metadata and destination-confirmed origin cleanup require a vector-free storage seam. This correction retains existing destination-first migration journals, publication authority, and strict vector search/write/donor checks without changing persisted schemas or public service protocols. Exact traceback and source reads ground the fallback after semantic code discovery failed during replacement.

## Steps

- [x] `S01` - Preserve terminal rebuild refusals and accurate watcher status through events, failures, and restart, and reconcile successful verified operator rebuilds; `watcher retry, controller, intake, execution and runtime, jobs.py completion hook, affected watcher and job tests`.
- [x] `S02` - Recover abandoned receipts before certification, preserve unsafe reader fences until explicit rebuild proof commit, and enforce proof before generation publication; `shared publication recovery and checkpoint owner, code/document/vault source entry paths, CPU real-storage recovery and ledger regression tests`.
- [x] `S03` - Stabilize membership identity by pruning unreachable ignore files and verify legitimate nested ignore changes still invalidate proof; `src/vaultspec_rag/indexer/_ignore_specs.py, ignore/policy regression tests`.
- [x] `S05` - Remove stale relevance-feedback anchors before hybrid or dense queries and verify search remains available after point replacement; `src/vaultspec_rag/_store_search.py and store search regression tests`.
- [x] `S06` - Report collection model or geometry incompatibility as terminal explicit-rebuild refusal and report the actual configured backend in service capabilities; `src/vaultspec_rag/store_runtime.py and capabilities.py, storage identity and service capability CPU regressions`.
- [x] `S07` - Require rebuild observation and generation creation after structural scope refusal so an in-flight or resumed older full sweep cannot erase lost scope; `watcher_retry_policy.py rebuild certification and real-ledger watcher rebuild reconciliation regressions`.
- [x] `S08` - Prove lifecycle target identity and process incarnation across stop, reclaim and reaping, preserve successor discovery during cleanup, and retain unknown machine presence on probe faults; `src/vaultspec_rag/_process_probe.py, _machine_lock.py, cli/_process.py, cli/_service_stop.py, cli/_service_start.py, cli/_status_render.py, serviceclient/_discovery.py and focused CPU lifecycle, machine presence, discovery cleanup and compatibility tests`.
- [ ] `S09` - Prevent CI resident restart while a dependent native attempt is active and roll out the corrected admission runtime after that attempt releases; `isolated ci-fleet resident, protected task compilation and fleet.yml probe declaration, engine/supervisor grant and preparation readiness, runtime/server wiring and affected CPU tests, resident-service ADR refinement and trusted idle local authority deployment`.
- [x] `S10` - Preserve canonical weighted-stream framing while resuming committed segment gaps, with real-ledger interrupted-run regressions and guarded boundary rejection; `indexer/_consumer_pipeline.py, _run_checkpoint.py, _slicing.py and _streaming_types.py as needed, focused CPU weighted stream and real-ledger resume tests`.
- [ ] `S11` - Allow vector-free cross-kind route reconciliation against an old-model origin without weakening destination evidence or vector conformance; `indexer/_route_migration.py, store_catalog.py and store_ingest.py plus collection owner only as needed, CPU real-Qdrant and ledger migration and strict conformance regressions`.
- [ ] `S04` - Deploy the current checkout as the resident daemon, repair affected publications through explicit rebuild jobs when required, and verify service health, search, and watcher convergence; `resident service lifecycle, affected root ledgers and admitted jobs, plan verification and final audit`.

## Parallelization

S01 and S02 may run concurrently with disjoint write ownership: the retry worker owns retry, controller settlement, and their tests; the recovery worker owns receipt recovery paths and their tests. The supervisor owns S03 and S05, the operator-job completion hook for S01, shared verification and serialized Git/vault mutations, and S04 service rollout. S04 follows all code repairs.

For S06 and S07, the supervisor owns S06 capability/collection projections and the watcher worker owns S07 rebuild observation cutoffs and their tests. They may run concurrently with disjoint write ownership. S04 rollout follows both; all Git/vault and live service mutations remain serialized under the supervisor.

For S08, the recovery worker owns lifecycle identity, machine presence and stop/start/status discovery cleanup paths and their CPU regressions. The supervisor owns live lifecycle operations, admission maintenance, Git/vault mutations, and final verification. S04 deployment loads S08 before publication repairs resume.

S09 runs in an isolated ci-fleet worktree. The watcher worker owns resident.py, protected task compilation in config.py, the shared engine/server/supervisor/runtime readiness wiring, fleet.yml probe-task declarations, and affected CPU tests. The supervisor owns the resident-service ADR refinement, runtime deployment, shared metadata and Git operations, and admission maintenance. S08 and S09 may run concurrently with disjoint repositories. No active native attempt is interrupted; authority deployment and resident start wait for its release.

For S10, the recovery worker owns resumed weighted-stream framing and checkpoint selection plus their CPU tests. S10 may run concurrently with S09 in disjoint repositories and S04 observation of existing admitted jobs. The supervisor owns all lifecycle, job-control, Git/vault and shared verification actions. Process-only mutation checks never change checkout source bytes. Deployment of S10 waits for controlled checkpoint settlement and then resumes jobs against its committed source.

S11 is assigned to the watcher worker in the monitor checkout, owning cross-kind route reconciliation and vector-free storage metadata/delete seams plus their CPU regressions. Its source paths are disjoint from S10 and may proceed concurrently. The supervisor owns all shared gates, vault/Git changes, runtime control and final rollout.

## Verification

Focused regression and integration checks establish terminal refusal through new events and restart, truthful controller status, abandoned-receipt recovery, and stable membership identity for ignored subtrees while preserving relevant nested ignores. Negative guards receive uninterrupted fail/pass mutation proof. Before each commit, run package lint, format checks, changed-file typing, and affected tests with separately captured exit codes. Final verification exercises the checkout daemon, affected roots, live search, watcher convergence, and lifecycle ownership. No changes are pushed or merged. Completion requires every Step closed and integrated review passing.
