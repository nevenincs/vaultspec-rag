---
tags:
  - '#plan'
  - '#incremental-publication-cost'
date: '2026-09-08'
tier: L3
related:
  - '[[2026-09-08-incremental-publication-cost-adr]]'
  - '[[2026-09-08-incremental-publication-cost-research]]'
  - '[[2026-09-08-incremental-publication-cost-reference]]'
modified: '2026-09-08'
body_schema: body-v2
body_hash: 'sha256:93c54460c73734aa86817e2cc7093a783fe5c36fa7c0255d25a54a37bd0e9eea'
---

# `incremental-publication-cost` plan

Replace corpus-wide publication scans and manifest rewrites with exact ledger-backed
deltas, recoverable receipts, and separately authorized verification.

## Description

Implement the amended normalized publication-proof model in four dependency-ordered Waves.
Wave 1 corrects proof identity and streaming intent contracts, establishes bounded normalized
ledger state, fences live readers, and delivers recoverable finalization. The compatibility
and authority Wave then migrates every proof consumer and establishes an operational exact
verification path before producer retirement. The source-adapter Wave routes code, document,
and vault publication through that shared owner without copying parent manifests, scanning
collection breadth, sweeping routes, or rewriting complete stat maps. The final Wave adds
deterministic proportionality guards, telemetry, fault injection, and performance evidence.
Existing explicit-reindex authority, source isolation, generation accounting, and
pointer-last replacement publication remain unchanged.

## Steps

## Wave `W01` - establish the durable proof authority

Deliver the normalized proof contract and durable receipt state machine required by every source adapter. All later Waves depend on it.

### Phase `W01.P01` - define proof values and exact delta algebra

Provide source-neutral immutable values for proof identity, path outcomes, aggregates, receipt states, provenance, and typed unverifiable outcomes.

- [x] `W01.P01.S01` - Define publication proof identities, path deltas, aggregate arithmetic, receipt states, provenance, and typed failures; `src/vaultspec_rag/indexer/_publication_proof.py`.
- [x] `W01.P01.S02` - Prove add, modify, delete, rename, empty, ignored, rejected, and no-op delta behavior; `src/vaultspec_rag/tests/test_publication_proof.py`.
- [ ] `W01.P01.S53` - Correct proof compatibility, streaming mutation, and reader-transition contracts; `src/vaultspec_rag/indexer/_publication_proof.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/tests/test_publication_proof.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.

### Phase `W01.P02` - persist normalized proofs and receipts

Give the run ledger normalized manifest rows, exact retained-point relations, aggregates, revisions, and idempotent prepare, apply, and commit operations without copying a parent manifest.

- [x] `W01.P02.S03` - Extend ledger value and schema contracts for proof revisions, rows, aggregates, receipts, and provenance; `src/vaultspec_rag/indexer/_run_ledger_models.py`.
- [ ] `W01.P02.S04` - Create and migrate normalized proof, receipt, mutation-unit, and tombstone tables with post-migration schema verification; `src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [ ] `W01.P02.S05` - Implement bounded proof reads, compare-and-swap revision commits, active-receipt lookup, read tokens, and canonical RunLedger composition; `src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py`.
- [ ] `W01.P02.S54` - Implement sparse active-manifest overrides, deletion tombstones, bounded effective reads, and retained-evidence ownership; `src/vaultspec_rag/indexer/_run_ledger_files.py, src/vaultspec_rag/indexer/_run_ledger_commits.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_route_migration.py`.
- [ ] `W01.P02.S55` - Remove eager parent-manifest copying and preserve live proof and receipt owners through compaction; `src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [ ] `W01.P02.S06` - Persist mutation intent before storage, confirm after acknowledgement, and replay or roll back deterministic retained-point units; `src/vaultspec_rag/indexer/_run_ledger_commits.py, src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_streaming_types.py`.
- [ ] `W01.P02.S07` - Prove additive migration, corrupt schema refusal, revision mismatch, tombstones, receipt replay, atomic proof commit, and zero-copy start; `src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [ ] `W01.P02.S08` - Prove active-receipt visibility and proof revision races across independent SQLite connections; `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`.

### Phase `W01.P03` - own recoverable publication finalization

Move proof preparation, confirmation, commit, and restart recovery into the shared finalization owner while retaining generation-last and pointer-last ordering.

- [ ] `W01.P03.S09` - Replace sidecar metadata transitions with receipt-backed proof reservation, unit confirmation, sealing, commit, and recovery; `src/vaultspec_rag/indexer/_checkpoint_common.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py`.
- [ ] `W01.P03.S10` - Enforce proof-before-generation finalization and bounded retention of receipt and evidence owners through compaction; `src/vaultspec_rag/indexer/_run_ledger_finalization.py`.
- [ ] `W01.P03.S11` - Prove shared transition ownership, parent mismatch refusal, and generation publication ordering; `src/vaultspec_rag/tests/test_checkpoint_common.py`.
- [ ] `W01.P03.S12` - Prove restart convergence for reserved receipts, partial mutation-unit states, sealed receipts, ingest-barrier ambiguity, immutable replay, authorized rollback, proof commit, and generation lag; `src/vaultspec_rag/tests/test_run_checkpoint.py`.
- [ ] `W01.P03.S56` - Split affected-path route reconciliation from explicitly authorized full collection sweeps; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/tests/integration/test_content_route_migration.py`.
- [ ] `W01.P03.S57` - Replace scoped full stat-evidence persistence with normalized changed-key updates; `src/vaultspec_rag/indexer/_stat_gate.py, src/vaultspec_rag/tests/test_stat_gate.py`.
- [ ] `W01.P03.S59` - Fence backend counts and queries with stable proof revisions, active-receipt absence, and every combined-source token; `src/vaultspec_rag/api.py, src/vaultspec_rag/_public_search.py, src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/tests/integration/test_search_publication_fence.py`.

## Wave `W03` - migrate proof consumers and exceptional verification

Stage every canonical proof reader, establish explicit verification and migration authority,
then flip the shared reader default before producer retirement. This Wave depends on Wave 1.

### Phase `W03.P07` - replace legacy completeness readers

Route every production consumer to canonical proof state without maintaining another authoritative manifest.

- [ ] `W03.P07.S67` - Create and test the shared compatibility-reader selector with a legacy default; `src/vaultspec_rag/_proof_reader_mode.py, src/vaultspec_rag/tests/test_proof_reader_mode.py`.
- [ ] `W03.P07.S28` - Stage a dormant proof-first breadth reader with pending-receipt checks, cheap counts, and typed legacy fallback; `src/vaultspec_rag/_index_breadth.py`.
- [ ] `W03.P07.S29` - Stage dormant cheap integrity reads and explicitly authorized exact identity and payload verification; `src/vaultspec_rag/_index_integrity.py`.
- [ ] `W03.P07.S30` - Stage dormant donor selection from compatible proof identity and retained-point evidence; `src/vaultspec_rag/indexer/_donor_candidates.py`.
- [ ] `W03.P07.S31` - Stage dormant proof-backed generation and storage surveys while classifying sidecars as migration artifacts; `src/vaultspec_rag/generation_survey.py, src/vaultspec_rag/storage_survey_ops.py`.
- [ ] `W03.P07.S32` - Stage dormant proof-backed reclamation, archive, and restore with consistent proof exports; `src/vaultspec_rag/storage_reclamation.py, src/vaultspec_rag/storage_manifest.py`.
- [ ] `W03.P07.S33` - Stage dormant proof and receipt cleanup before collection deletion; `src/vaultspec_rag/api.py`.
- [ ] `W03.P07.S34` - Prove breadth readers distinguish missing, incompatible, delta-derived, and fully verified proof; `src/vaultspec_rag/tests/test_indexer_unit.py`.
- [ ] `W03.P07.S35` - Prove integrity verification detects missing, extra, foreign, incompatible, and partial backend state; `src/vaultspec_rag/tests/test_index_integrity.py`.
- [ ] `W03.P07.S36` - Prove donor selection refuses incompatible or unverifiable proof ancestry; `src/vaultspec_rag/tests/test_donor_candidates.py`.
- [ ] `W03.P07.S61` - Prove proof-first survey, reclamation, archive, restore, and cleanup behavior across legacy cutover; `src/vaultspec_rag/tests/test_generation_survey.py, src/vaultspec_rag/tests/test_storage_survey.py, src/vaultspec_rag/tests/test_storage_manifest.py, src/vaultspec_rag/tests/test_storage_restore.py, src/vaultspec_rag/tests/integration/test_generation_reclaim.py, src/vaultspec_rag/tests/test_api_clean_admission.py`.

### Phase `W03.P08` - authorize migration and full verification

Ensure legacy evidence can seed canonical proof only through an explicit and separately measured operation.

- [ ] `W03.P08.S37` - Encode persisted publication, rebuild, migration, and exact-verification authority independently of run mode; `src/vaultspec_rag/indexer/_run_ledger_models.py`.
- [ ] `W03.P08.S52` - Carry explicit publication and verification authority through every persisted job contract and transition; `src/vaultspec_rag/job_models.py, src/vaultspec_rag/job_manager/models.py, src/vaultspec_rag/job_manager/_control.py, src/vaultspec_rag/job_manager/_execution.py, src/vaultspec_rag/job_manager/_persistence.py, src/vaultspec_rag/job_persistence.py`.
- [ ] `W03.P08.S38` - Route generic service and job creation through explicit authority without widening scoped publication; `src/vaultspec_rag/server/_routes.py, src/vaultspec_rag/server/_routes_reindex.py, src/vaultspec_rag/job_dispatch.py`.
- [ ] `W03.P08.S39` - Route CLI rebuild and verification requests through explicit authority without granting scoped scan permission; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W03.P08.S60` - Commit normalized proof only from successful explicitly authorized exact verification or migration and report scanned breadth; `src/vaultspec_rag/_index_integrity.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/tests/test_index_integrity.py`.
- [ ] `W03.P08.S40` - Prove legacy, missing-ancestry, schema-drift, and corrupt-receipt cases require explicit authority; `src/vaultspec_rag/tests/test_document_index_escalation.py`.
- [ ] `W03.P08.S62` - Prove explicit authority survives serialization, retry, restart, generic service admission, and CLI admission; `src/vaultspec_rag/tests/test_job_contracts_persistence.py, src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py, src/vaultspec_rag/tests/test_cli_index.py`.
- [ ] `W03.P08.S58` - Flip the shared compatibility-reader default to canonical proof and guard against legacy authority after cutover; `src/vaultspec_rag/_proof_reader_mode.py, src/vaultspec_rag/tests/test_process_probe_ownership_guards.py, src/vaultspec_rag/tests/test_indexer_unit.py`.

## Wave `W02` - adopt exact deltas in each source adapter

Translate code, document, and vault outcomes into the shared proof authority while preserving
source-specific classification and payload rules. This Wave depends on Waves 1 and 3.

### Phase `W02.P04` - migrate code publication

Remove full code metadata cloning and publication-time collection breadth scans from scoped code indexing.

- [ ] `W02.P04.S13` - Prepare code mutation units before writes, remove complete retained-ID materialization, and reconcile stale membership only for affected identities; `src/vaultspec_rag/indexer/_incremental_commit.py, src/vaultspec_rag/indexer/_consumer_pipeline.py`.
- [ ] `W02.P04.S14` - Publish code aggregates without full counts or full route reconciliation while retaining pointer-last replacement ordering; `src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [ ] `W02.P04.S15` - Emit exact changed-path outcomes instead of cloning and rewriting the complete prior metadata map; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P04.S16` - Retain code sidecars only as bounded legacy migration input and remove authoritative writes; `src/vaultspec_rag/indexer/_code_meta.py`.
- [ ] `W02.P04.S17` - Prove scoped code outcomes, interruption, replay, and retained-identity work bounded by affected paths and points; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.

### Phase `W02.P05` - migrate document publication

Replace full document manifest reconstruction with exact per-document proof updates.

- [ ] `W02.P05.S18` - Translate document streaming writes and pre-delete intent into shared proof deltas and receipt units; `src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_streaming.py`.
- [ ] `W02.P05.S19` - Consume canonical proof state for scoped document decisions without materializing a complete manifest; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W02.P05.S20` - Retain document sidecars only for legacy migration and remove authoritative full-manifest publication; `src/vaultspec_rag/indexer/_document_meta.py`.
- [ ] `W02.P05.S21` - Prove document checkpoint delta translation and restart recovery; `src/vaultspec_rag/tests/test_document_checkpoint.py`.
- [ ] `W02.P05.S22` - Prove document add, modify, delete, rename, empty, ignored, no-op, and interrupted publication; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.

### Phase `W02.P06` - migrate vault publication

Remove complete prior-map copying and full stored-identity breadth scans from scoped vault indexing.

- [ ] `W02.P06.S23` - Add a vault publication-checkpoint adapter for vector, payload-only, tail-delete, and document-delete receipt units; `src/vaultspec_rag/indexer/_vault_incremental.py, src/vaultspec_rag/indexer/_vault_checkpoint.py`.
- [ ] `W02.P06.S24` - Give vault the shared ledger owner and commit exact proof breadth without get_all_ids or complete hash-map rewrites; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `W02.P06.S25` - Retain vault metadata only as bounded legacy migration input and remove authoritative fields; `src/vaultspec_rag/indexer/_vault_meta.py`.
- [ ] `W02.P06.S26` - Prove true incremental vault publication and metadata-only updates against canonical proof state; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W02.P06.S27` - Prove exact vault breadth across deletion, interruption, and restart; `src/vaultspec_rag/tests/integration/test_vault_breadth_publication.py`.

### Phase `W02.P11` - verify cross-source replacement publication

Verify replacement proof and served-pointer ordering only after code, document, and vault adapters are complete.

- [ ] `W02.P11.S41` - Prove replacement verification commits proof before moving the served pointer; `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.

## Wave `W04` - prove proportionality and operational visibility

Add deterministic regression guards, fault injection, telemetry, and end-to-end verification. This Wave depends on Waves 1 through 3.

### Phase `W04.P09` - expose publication cost telemetry

Report changed identities, proof rows, backend point operations, phase timings, and full-verification breadth through stable result surfaces.

- [ ] `W04.P09.S42` - Define the thread-safe publication metrics accumulator, stable result contract, and shared streaming hook; `src/vaultspec_rag/indexer/_vault_prep.py, src/vaultspec_rag/indexer/_publication_metrics.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/indexer/_streaming.py`.
- [ ] `W04.P09.S63` - Wire code counters and timings through streaming, deletion, rollback, proof commit, pointer publication, and result construction; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_consumer_pipeline.py, src/vaultspec_rag/indexer/_incremental_commit.py, src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [ ] `W04.P09.S64` - Wire document publication counters and timings through every document writer and result construction; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_document_checkpoint.py`.
- [ ] `W04.P09.S65` - Wire vault publication counters and timings through full and incremental writers and result construction; `src/vaultspec_rag/indexer/_vault_indexer.py, src/vaultspec_rag/indexer/_vault_incremental.py`.
- [ ] `W04.P09.S43` - Project publication and verification telemetry into the stable CLI result row; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W04.P09.S44` - Preserve publication telemetry through execution, watcher execution, terminal transitions, snapshots, dispatch, and durable persistence; `src/vaultspec_rag/job_dispatch.py, src/vaultspec_rag/job_models.py, src/vaultspec_rag/job_manager/models.py, src/vaultspec_rag/job_manager/_control.py, src/vaultspec_rag/job_manager/_execution.py, src/vaultspec_rag/job_manager/_persistence.py, src/vaultspec_rag/job_persistence.py, src/vaultspec_rag/watcher_execution.py`.
- [ ] `W04.P09.S45` - Prove stable CLI output for incremental and full-verification cost fields; `src/vaultspec_rag/tests/test_cli_index.py`.
- [ ] `W04.P09.S46` - Prove service indexing results retain source-scoped publication telemetry; `src/vaultspec_rag/tests/integration/test_index_reuse_daemon_path.py`.
- [ ] `W04.P09.S66` - Prove telemetry survives terminal execution, durable reload, watcher execution, and daemon reuse; `src/vaultspec_rag/tests/test_job_contracts_persistence.py, src/vaultspec_rag/tests/test_watcher_unit.py, src/vaultspec_rag/tests/integration/test_index_reuse_daemon_path.py`.

### Phase `W04.P10` - install architectural and cost guards

Make corpus-wide work in scoped publication fail deterministically and demonstrate that the guards can fail.

- [ ] `W04.P10.S47` - Guard single proof ownership and forbid scoped full scans, route sweeps, retained-ID materialization, and complete map serialization; `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.
- [ ] `W04.P10.S48` - Prove scoped code counts and retained-identity work remain proportional to affected identities and points; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [ ] `W04.P10.S49` - Prove scoped document operation counts remain proportional to changed identities and retained points; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.
- [ ] `W04.P10.S50` - Prove scoped vault operation counts remain proportional to changed identities and points; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W04.P10.S51` - Add a large-parent single-path benchmark for writer-lease and publication-cost regression; `src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`.

## Parallelization

Waves execute in document order: W01, W03, W02, then W04. The Wave 1 critical path is S53,
S04, S05, S54, S55, S06, S07 and S08, S09, S10, S11 and S12, then S59. S56 and S57 may
proceed after the shared proof API stabilizes but must finish before source cutover. In W03,
proof consumer migrations may execute concurrently after the canonical reader stabilizes;
S37 precedes S52, which precedes S38 and S39, while S60 establishes proof before failure-path
tests and S58 closes the cutover. P04, P05, and P06 may execute in parallel only after
streaming hooks, bounded route reconciliation, changed-key stat evidence, reader fencing,
compatibility readers, and explicit recovery authority are complete. S41 follows completed
replacement publication. In W04, telemetry propagation and source-specific proportionality
tests may run in parallel after the result shape is fixed. Shared seams
`_checkpoint_common.py`, `_run_ledger_runtime.py`, `_index_breadth.py`, and
`_vault_prep.py` are never edited concurrently.

## Verification

- Unit gates pass for proof algebra, ledger persistence and migration, checkpoint
  transitions, receipt recovery, and concurrency.
- Code, document, and vault integration gates cover add, modify, delete, rename, empty,
  ignored or rejected, no-op, interruption, replay, and rebuild behavior.
- Scoped publication performs no collection-wide scroll, distinct-identity scan,
  parent-manifest copy, complete retained-ID materialization, complete sidecar or stat-evidence
  serialization, unbounded ancestry read, or full route sweep.
- Mutation intent is durable before every store write, storage confirmation follows the
  backend barrier, and proof commit compare-and-swaps the expected parent revision only after
  all sealed units are confirmed.
- A backend query that overlaps receipt preparation, confirmation, proof commit, or revision
  change never accepts mixed storage and proof state.
- Recovery gates cover reserved and sealed receipts, partial prepared, applied, and confirmed
  mutation-unit sets, ingest-barrier ambiguity, immutable replay material, source-change
  refusal, deterministic replay, and explicitly authorized rollback.
- Concurrent search gates fence both count and query, and combined search validates every
  participating source token before accepting results.
- Operation counts remain proportional to changed identities and point mutations as total
  corpus size grows; large-index elapsed budgets cover writer-lease duration.
- Full verification is reachable only through persisted explicit rebuild, migration, or
  audit authority and reports scanned breadth separately; recovery alone cannot grant a scan.
- Replacement proof commits before the served pointer advances, and failed replacement
  leaves the prior generation served.
- Legacy sidecars are bounded migration input only and are never dual-written as an
  independent authority.
- Backend, collection, schema, source, membership, content, policy, active-receipt, and parent
  revision mismatch cases fail closed with typed outcomes; publication generation remains
  provenance rather than compatibility.
- Every guard and negative test is mutation-proven red on its intended assertion and green
  after restoration, with both directions recorded in the test.
- Formatting, lint, strict type checks, targeted unit and integration suites, benchmark
  gates, `vaultspec-core vault plan check`, and `vaultspec-core vault check all` pass
  explicitly before closeout.
- A formal `vaultspec-code-review` finds no blocking safety, intent, or quality defects.
