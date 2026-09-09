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
modified: '2026-09-09'
body_schema: body-v2
body_hash: 'sha256:d3925811c99ff564555d3eda26c9e7929db705704775d38c9d270a18f65a317f'
---

<!-- RETIRED: S13, S14, S15, S18, S19, S23, S24 -->

# `incremental-publication-cost` plan

Replace corpus-wide publication scans and manifest rewrites with exact ledger-backed
deltas, recoverable receipts, and separately authorized verification.

## Description

Implement the amended normalized publication-proof model in four dependency-ordered Waves.
Wave 1 corrects proof identity and streaming intent contracts, rejects every pre-proof
ledger without mutation, establishes bounded canonical state, and delivers recoverable
finalization. The authority and reader Wave makes rebuild remediation operational before
cutting every consumer directly to canonical proof; old formats fail closed and no selector,
fallback, translation, or seeding path exists. The producer Wave then routes code, document,
and vault publication through that sole owner and deletes sidecar and generation-manifest
code. The final Wave adds deterministic proportionality guards, telemetry, fault injection,
and performance evidence. Existing explicit-reindex authority, source isolation, generation
accounting, and pointer-last replacement publication remain unchanged. W03 reader cutover
and W02 producer cutover are one release boundary; no intermediate build is released.

## Steps

## Wave `W01` - establish the durable proof authority

Deliver the normalized proof contract and durable receipt state machine required by every source adapter. All later Waves depend on it.

### Phase `W01.P01` - define proof values and exact delta algebra

Provide source-neutral immutable values for proof identity, path outcomes, aggregates, receipt states, provenance, and typed unverifiable outcomes.

- [x] `W01.P01.S01` - Define publication proof identities, path deltas, aggregate arithmetic, receipt states, provenance, and typed failures; `src/vaultspec_rag/indexer/_publication_proof.py`.
- [x] `W01.P01.S02` - Prove add, modify, delete, rename, empty, ignored, rejected, and no-op delta behavior; `src/vaultspec_rag/tests/test_publication_proof.py`.
- [x] `W01.P01.S53` - Correct proof compatibility, streaming mutation, and reader-transition contracts; `src/vaultspec_rag/indexer/_publication_proof.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/tests/test_publication_proof.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.

### Phase `W01.P02` - persist current-format proofs and receipts

Give the run ledger exact current-format proof rows, receipts, receipt-bound active state, and typed old-format refusal needed before canonical reader and producer cutover.

- [x] `W01.P02.S03` - Extend ledger value and schema contracts for proof revisions, rows, aggregates, receipts, and provenance; `src/vaultspec_rag/indexer/_run_ledger_models.py`.
- [x] `W01.P02.S04` - Create and migrate normalized proof, receipt, mutation-unit, and tombstone tables with post-migration schema verification; `src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [x] `W01.P02.S05` - Implement bounded proof reads, compare-and-swap revision commits, active-receipt lookup, read tokens, and canonical RunLedger composition; `src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [x] `W01.P02.S68` - Hard-bump and gate the publication ledger format, create only an empty current schema, reject old or pre-proof databases without mutation, and remove legacy proof statuses; `src/vaultspec_rag/indexer/_publication_proof.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/tests/test_publication_proof.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [x] `W01.P02.S70` - Require backend identity in run signatures and checkpoint requests, delete legacy defaults and decoder fallbacks, and update every constructor; `src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/tests/test_checkpoint_common.py, src/vaultspec_rag/tests/test_config_epoch.py, src/vaultspec_rag/tests/test_document_index_escalation.py, src/vaultspec_rag/tests/test_index_run_ledger.py, src/vaultspec_rag/tests/test_run_checkpoint.py, src/vaultspec_rag/tests/test_document_checkpoint.py, src/vaultspec_rag/tests/integration/test_document_watcher.py, src/vaultspec_rag/tests/integration/test_content_kind_restart.py, src/vaultspec_rag/tests/integration/test_content_route_migration.py, src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.
- [x] `W01.P02.S06` - Persist mutation intent before storage, confirm after acknowledgement, and replay or roll back deterministic retained-point units; `src/vaultspec_rag/indexer/_publication_proof.py, src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/indexer/_run_ledger_commits.py, src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_streaming_types.py, src/vaultspec_rag/tests/test_index_run_ledger.py, src/vaultspec_rag/tests/test_slice_writer_overlap.py`.
- [x] `W01.P02.S54` - Implement receipt-bound single-snapshot canonical-proof reads with sparse run-local overrides, deletion tombstones, bounded path and candidate inputs, and exact retained-point ownership without generation ancestry or a second authority; `src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/indexer/_run_ledger_files.py, src/vaultspec_rag/indexer/_run_ledger_commits.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/tests/test_index_run_ledger.py, src/vaultspec_rag/tests/test_run_checkpoint.py, src/vaultspec_rag/tests/test_document_checkpoint.py, src/vaultspec_rag/tests/integration/test_content_route_migration.py`.
- [x] `W01.P02.S07` - Prove exact current-schema creation, typed rebuild refusal for old formats, corrupt-schema refusal, revision mismatch, tombstones, receipt replay, atomic proof commit, and zero-copy start; `src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [x] `W01.P02.S08` - Prove active-receipt visibility and proof revision races across independent SQLite connections; `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`.

### Phase `W01.P03` - enforce proof retention and finalization

Make proof finalization and compaction preserve every current proof, retained-evidence owner, and open receipt while bounding eligible closed history.

- [x] `W01.P03.S10` - Provide a strict proof-before-generation finalization gate, bound eligible closed receipt history, and preserve current proof, evidence, and open-receipt owners through compaction; `src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.

## Wave `W03` - authorize rebuild and cut over canonical proof readers

Make rebuild and non-seeding audit authority operational, then move every proof consumer directly to canonical proof with typed rebuild-required refusal and no selector, fallback, or sidecar translation. This Wave depends on Wave 1.

### Phase `W03.P08` - authorize rebuild and non-seeding verification

Ensure old or missing proof can only be replaced by an explicit rebuild while audit verification checks existing canonical proof without creating or repairing it.

- [x] `W03.P08.S37` - Encode persisted publication, rebuild, and audit-verification authority independently of run mode without migration authority; `src/vaultspec_rag/indexer/_run_ledger_models.py, src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [x] `W03.P08.S52` - Carry required publication and verification authority through the exact job codec, every production constructor, immutable transition, and attempt context; `src/vaultspec_rag/job_models.py, src/vaultspec_rag/job_manager/models.py, src/vaultspec_rag/job_manager/_control.py, src/vaultspec_rag/job_manager/_execution.py, src/vaultspec_rag/job_manager/_persistence.py, src/vaultspec_rag/job_persistence.py, src/vaultspec_rag/_job_admission.py, src/vaultspec_rag/jobs.py, src/vaultspec_rag/server/_routes.py, src/vaultspec_rag/server/_routes_reindex.py, src/vaultspec_rag/serviceclient/_transport.py, src/vaultspec_rag/watcher_execution.py, src/vaultspec_rag/tests`.
- [x] `W03.P08.S38` - Enforce authority-specific execution admission for generic service jobs without widening scoped publication; `src/vaultspec_rag/job_dispatch.py, src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py, src/vaultspec_rag/tests/integration/test_document_execution.py, src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`.
- [x] `W03.P08.S39` - Require CLI publication and rebuild requests to carry explicit authority through the reindex transport and validate it without granting scoped scan permission; `src/vaultspec_rag/cli/_index.py, src/vaultspec_rag/serviceclient/_transport.py, src/vaultspec_rag/server/_routes_reindex.py, src/vaultspec_rag/mcp/_tools.py, src/vaultspec_rag/_integrity_remediation.py, src/vaultspec_rag/tests/test_integrity_remediation.py, src/vaultspec_rag/tests`.
- [ ] `W03.P08.S60` - Implement and activate CLI audit verification against existing canonical proof without creating or repairing proof, and permit only rebuild publication to establish missing proof; `src/vaultspec_rag/_index_integrity.py, src/vaultspec_rag/cli/_index.py, src/vaultspec_rag/tests/test_index_integrity.py, src/vaultspec_rag/tests/test_cli_index.py`.
- [ ] `W03.P08.S40` - Prove missing or old-format proof, schema drift, and corrupt receipts require typed rebuild refusal and that audit verification cannot seed proof; `src/vaultspec_rag/tests/test_document_index_escalation.py`.
- [ ] `W03.P08.S62` - Prove explicit authority survives serialization, retry, restart, generic service admission, and CLI admission; `src/vaultspec_rag/tests/test_job_contracts_persistence.py, src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py, src/vaultspec_rag/tests/test_cli_index.py`.

### Phase `W03.P07` - cut over canonical proof readers

Route every production consumer directly to canonical proof, fail old formats closed, and remove selector, fallback, and sidecar-read authority.

- [ ] `W03.P07.S28` - Replace breadth reads with canonical proof aggregates, pending-receipt checks, cheap counts, and typed rebuild-required refusal for absent or old-format proof; `src/vaultspec_rag/_index_breadth.py`.
- [ ] `W03.P07.S29` - Replace integrity reads with canonical proof and keep explicitly authorized audit verification non-seeding; `src/vaultspec_rag/_index_integrity.py`.
- [ ] `W03.P07.S30` - Replace donor selection with compatible canonical proof identity and retained-point evidence; `src/vaultspec_rag/indexer/_donor_candidates.py`.
- [ ] `W03.P07.S31` - Replace generation and storage surveys with canonical proof and remove sidecar decoding from those consumers; `src/vaultspec_rag/generation_survey.py, src/vaultspec_rag/storage_survey_ops.py`.
- [ ] `W03.P07.S32` - Replace reclamation, archive, and restore with canonical proof exports and refuse old sidecar-only artifacts without import or translation; `src/vaultspec_rag/storage_reclamation.py, src/vaultspec_rag/storage_manifest.py`.
- [ ] `W03.P07.S33` - Replace cleanup admission with canonical proof and receipt cleanup before collection deletion without sidecar fallback; `src/vaultspec_rag/api.py`.
- [ ] `W03.P07.S59` - Fence backend counts and queries with stable proof revisions, active-receipt absence, and every combined-source token; `src/vaultspec_rag/api.py, src/vaultspec_rag/_public_search.py, src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/tests/integration/test_search_publication_fence.py`.
- [ ] `W03.P07.S34` - Prove breadth readers distinguish missing, incompatible, delta-derived, and fully verified proof; `src/vaultspec_rag/tests/test_indexer_unit.py`.
- [ ] `W03.P07.S35` - Prove integrity verification detects missing, extra, foreign, incompatible, and partial backend state; `src/vaultspec_rag/tests/test_index_integrity.py`.
- [ ] `W03.P07.S36` - Prove donor selection refuses incompatible or unverifiable proof ancestry; `src/vaultspec_rag/tests/test_donor_candidates.py`.
- [ ] `W03.P07.S61` - Prove canonical-only survey, reclamation, archive, restore, and cleanup behavior, typed rebuild refusal, and absence of sidecar translation; `src/vaultspec_rag/tests/test_generation_survey.py, src/vaultspec_rag/tests/test_storage_survey.py, src/vaultspec_rag/tests/test_storage_manifest.py, src/vaultspec_rag/tests/test_storage_restore.py, src/vaultspec_rag/tests/integration/test_generation_reclaim.py, src/vaultspec_rag/tests/test_api_clean_admission.py`.
- [ ] `W03.P07.S67` - Prove absent or old-format proof yields typed rebuild-required and no reader selector, fallback, shim, alias, or compatibility export exists; `src/vaultspec_rag/tests/test_indexer_unit.py, src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.
- [ ] `W03.P07.S58` - Complete the direct reader cutover and guard that no proof consumer uses a selector, fallback, sidecar reader, migration path, or compatibility export; `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py, src/vaultspec_rag/tests/test_indexer_unit.py`.

## Wave `W02` - cut over canonical proof producers

Translate code, document, and vault outcomes into the sole canonical proof authority and delete sidecar writers and models. This Wave depends on Waves 1 and 3.

### Phase `W02.P12` - activate shared canonical publication

Replace shared checkpoint, routing, and stat-evidence publication only after every reader fails closed on missing canonical proof.

- [ ] `W02.P12.S56` - Split affected-path route reconciliation from explicitly authorized full collection sweeps; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/tests/integration/test_content_route_migration.py`.
- [ ] `W02.P12.S57` - Replace scoped full stat-evidence persistence with normalized changed-key updates; `src/vaultspec_rag/indexer/_stat_gate.py, src/vaultspec_rag/tests/test_stat_gate.py`.
- [ ] `W02.P12.S09` - Implement source-neutral receipt-backed proof finalization and recovery primitives and atomically activate the strict proof-before-generation gate with canonical checkpoint producer cutover, without sidecar access or a compatibility branch; `src/vaultspec_rag/indexer/_checkpoint_common.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py`.
- [ ] `W02.P12.S11` - Prove shared transition ownership, parent mismatch refusal, and generation publication ordering; `src/vaultspec_rag/tests/test_checkpoint_common.py`.
- [ ] `W02.P12.S12` - Prove restart convergence for reserved receipts, partial mutation-unit states, sealed receipts, ingest-barrier ambiguity, immutable replay, authorized rollback, proof commit, and generation lag; `src/vaultspec_rag/tests/test_run_checkpoint.py`.

### Phase `W02.P04` - cut over code publication

Replace full code metadata cloning and publication-time collection breadth scans with canonical proof deltas, then delete code sidecar production.

- [ ] `W02.P04.S16` - Atomically switch code mutation, aggregate, changed-path, and pointer-last publication to canonical receipts and proof, then delete code sidecar parsing, writing, models, and imports; `src/vaultspec_rag/indexer/_incremental_commit.py, src/vaultspec_rag/indexer/_consumer_pipeline.py, src/vaultspec_rag/indexer/_generation_lifecycle.py, src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_code_meta.py, src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [ ] `W02.P04.S17` - Prove scoped code outcomes, interruption, replay, and retained-identity work bounded by affected paths and points; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.

### Phase `W02.P05` - cut over document publication

Replace full document manifest reconstruction with exact canonical per-document proof updates, then delete document sidecar production.

- [ ] `W02.P05.S20` - Atomically switch document streaming, deletion, checkpoint, and scoped decisions to canonical receipts and proof, then delete document sidecar parsing, writing, models, and imports; `src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_document_meta.py, src/vaultspec_rag/tests/test_document_checkpoint.py, src/vaultspec_rag/tests/integration/test_document_indexing.py`.
- [ ] `W02.P05.S21` - Prove document checkpoint delta translation and restart recovery; `src/vaultspec_rag/tests/test_document_checkpoint.py`.
- [ ] `W02.P05.S22` - Prove document add, modify, delete, rename, empty, ignored, no-op, and interrupted publication; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.

### Phase `W02.P06` - cut over vault publication

Replace complete prior-map copying and full stored-identity scans with canonical vault proof updates, then delete vault sidecar production.

- [ ] `W02.P06.S25` - Atomically switch vault vector, payload, deletion, aggregate, and scoped publication to canonical receipts and proof, then delete vault sidecar parsing, writing, models, and imports; `src/vaultspec_rag/indexer/_vault_incremental.py, src/vaultspec_rag/indexer/_vault_checkpoint.py, src/vaultspec_rag/indexer/_vault_indexer.py, src/vaultspec_rag/indexer/_vault_meta.py, src/vaultspec_rag/tests/integration/test_vault_true_incremental.py, src/vaultspec_rag/tests/integration/test_vault_breadth_publication.py`.
- [ ] `W02.P06.S26` - Prove true incremental vault publication and metadata-only updates against canonical proof state; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W02.P06.S27` - Prove exact vault breadth across deletion, interruption, and restart; `src/vaultspec_rag/tests/integration/test_vault_breadth_publication.py`.

### Phase `W02.P11` - complete canonical-only publication

Delete generation-manifest ancestry, prove no legacy publication path remains, and verify replacement ordering after all three canonical producers are complete.

- [ ] `W02.P11.S55` - Delete eager parent-manifest copying, full-manifest iterators and callers, and file-state ancestry after canonical producers replace them; `src/vaultspec_rag/indexer/_run_ledger_runtime.py, src/vaultspec_rag/indexer/_run_ledger_files.py, src/vaultspec_rag/indexer/_run_ledger_commits.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_consumer_pipeline.py, src/vaultspec_rag/indexer/_generation_lifecycle.py, src/vaultspec_rag/tests/test_index_run_ledger.py, src/vaultspec_rag/tests/test_run_checkpoint.py, src/vaultspec_rag/tests/test_document_checkpoint.py, src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [ ] `W02.P11.S69` - Prove the source tree contains no sidecar authority, fallback reader, migration or seeding path, legacy status or signature default, shim, alias, or deprecated compatibility export; `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.
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

- [ ] `W04.P10.S47` - Guard single proof ownership and forbid selectors, fallbacks, sidecar authority, migration or seeding, scoped full scans, route sweeps, retained-ID materialization, and complete map serialization; `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.
- [ ] `W04.P10.S48` - Prove scoped code counts and retained-identity work remain proportional to affected identities and points; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [ ] `W04.P10.S49` - Prove scoped document operation counts remain proportional to changed identities and retained points; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.
- [ ] `W04.P10.S50` - Prove scoped vault operation counts remain proportional to changed identities and points; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W04.P10.S51` - Add a large-parent single-path benchmark for writer-lease and publication-cost regression; `src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`.

## Parallelization

Waves execute in document order: W01, W03, W02, then W04. The Wave 1 critical path is S53,
S04, S05, S68, S70, S06, S54, S07 and S08, then S10. S68 and S70 are corrective Steps over
completed history; closed S01 through S05 remain intact. In W03, P08 precedes P07 so explicit
rebuild remediation exists before readers begin failing old formats closed. S37 precedes S52,
which precedes S38 and S39; S60 remains non-seeding, and S40 proves that boundary. Direct
consumer Steps S28 through S33 and S59 may proceed by isolated ownership, their proof Steps
follow, and S58 closes the reader cutover without a selector or fallback. In W02, S56 and S57
precede S09, followed by S11 and S12; P04, P05, and P06 may then execute in parallel. S55
deletes copy and full-manifest paths only after every canonical producer has replaced them,
S69 proves no obsolete authority remains, and S41 verifies replacement publication last. In
W04, telemetry propagation and source-specific proportionality tests may run in parallel
after the result shape is fixed. Shared seams
`_checkpoint_common.py`, `_run_ledger_runtime.py`, `_index_breadth.py`, and
`_vault_prep.py` are never edited concurrently. W03 and W02 may use separate reviewed
commits, but no release or deployment boundary exists between them.

## Verification

- Unit gates pass for proof algebra, exact current-schema creation, typed no-mutation refusal
  of old ledgers, checkpoint transitions, receipt recovery, and concurrency.
- Code, document, and vault integration gates cover add, modify, delete, rename, empty,
  ignored or rejected, no-op, interruption, replay, and rebuild behavior.
- Scoped publication performs no collection-wide scroll, distinct-identity scan,
  parent-manifest copy, complete retained-ID materialization, complete sidecar or stat-evidence
  serialization, unbounded ancestry read, or full route sweep.
- Mutation intent is durable before every store write, storage confirmation follows the
  backend barrier, and proof commit compare-and-swaps the expected parent revision only after
  all sealed units are confirmed.
- Effective path and candidate reads use one receipt-bound ledger snapshot, canonical proof
  plus run-local overrides and tombstones, bounded inputs, and no recursive generation walk
  or full effective-manifest iterator.
- A backend query that overlaps receipt preparation, confirmation, proof commit, or revision
  change never accepts mixed storage and proof state.
- Recovery gates cover reserved and sealed receipts, partial prepared, applied, and confirmed
  mutation-unit sets, ingest-barrier ambiguity, immutable replay material, source-change
  refusal, deterministic replay, and explicitly authorized rollback.
- Concurrent search gates fence both count and query, and combined search validates every
  participating source token before accepting results.
- Operation counts remain proportional to changed identities and point mutations as total
  corpus size grows; large-index elapsed budgets cover writer-lease duration.
- Full source reconstruction is reachable only through persisted explicit rebuild authority.
  Audit verification reports scanned breadth separately, requires existing canonical proof,
  and cannot seed or repair missing proof; recovery alone cannot grant a scan.
- Replacement proof commits before the served pointer advances, and failed replacement
  leaves the prior generation served.
- Old ledgers, sidecars, archives, signatures, and statuses are never read, translated,
  migrated, seeded, dual-written, or exposed through selectors, fallbacks, shims, aliases,
  or deprecated re-exports; they fail closed with typed rebuild-required remediation.
- Release packaging cannot select a state between W03 direct reader cutover and completed
  W02 canonical producers, sidecar deletion, S55 ancestry removal, and S69 guard closure.
- Compaction preserves the current proof generation, every retained-evidence owner, and every
  open-receipt owner, bounds eligible closed receipt history, and retains no file-state
  ancestry solely for compatibility.
- Backend, collection, schema, source, membership, content, policy, active-receipt, and parent
  revision mismatch cases fail closed with typed outcomes; publication generation remains
  provenance rather than compatibility.
- Every guard and negative test is mutation-proven red on its intended assertion and green
  after restoration, with both directions recorded in the test.
- Formatting, lint, strict type checks, targeted unit and integration suites, benchmark
  gates, `vaultspec-core vault plan check`, and `vaultspec-core vault check all` pass
  explicitly before closeout.
- A formal `vaultspec-code-review` finds no blocking safety, intent, or quality defects.
