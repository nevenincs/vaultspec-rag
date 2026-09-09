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
body_hash: 'sha256:c8b0ebb15b47d8d7d168de99ef1100a0d83e6b9b5d508dcdb3b2df412238dcfa'
---

<!-- RETIRED: P04, P05, P06, P07, P09, P10, P11, P12, S09, S11, S12, S13, S14, S15, S16, S17, S18, S19, S20, S21, S22, S23, S24, S25, S26, S27, S28, S29, S30, S31, S32, S33, S34, S35, S36, S41, S42, S43, S44, S45, S46, S47, S48, S49, S50, S51, S55, S56, S57, S58, S59, S61, S63, S64, S65, S66, S67, S69 -->

# `incremental-publication-cost` plan

Replace corpus-wide publication scans and manifest rewrites with exact ledger-backed
deltas, recoverable receipts, and separately authorized verification.

## Description

Finish issue 469 by changing the production hot paths, not by accumulating proof-of-process
steps. The canonical proof, receipt, schema, authority, and audit foundation is already built.
The remaining work is seven cohesive slices: cut all runtime readers directly to canonical
proof; replace the shared scoped finalization path; switch code, document, and vault
publication; delete the displaced manifest, sidecar, fallback, and full-scan implementation;
then verify the finished system once against observable cost and correctness criteria.

The pull request succeeds when a small incremental change performs work proportional to its
changed identities and point mutations, survives interruption, and leaves no old publication
authority in the source tree. Plan completion is bookkeeping, not a success criterion.

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
- [x] `W03.P08.S60` - Implement and activate service-owned CLI full audit verification using an atomic current-proof snapshot and bounded backend payload scans without creating or repairing proof, and permit only rebuild publication to establish missing proof; `src/vaultspec_rag/_index_integrity.py, src/vaultspec_rag/cli/_index.py, src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/store_catalog.py, src/vaultspec_rag/serviceclient/_transport.py, src/vaultspec_rag/server/_routes_reindex.py, src/vaultspec_rag/server/_routes.py, src/vaultspec_rag/tests/test_index_integrity.py, src/vaultspec_rag/tests/test_cli_index.py, src/vaultspec_rag/tests/test_server_routes.py, src/vaultspec_rag/tests/test_store.py`.
- [x] `W03.P08.S40` - Prove missing or old-format proof, schema drift, and corrupt receipts require typed rebuild refusal and that audit verification cannot seed proof; `src/vaultspec_rag/indexer/_run_ledger_publication.py, src/vaultspec_rag/tests/test_document_index_escalation.py`.
- [x] `W03.P08.S62` - Prove explicit authority survives serialization, retry, restart, generic service admission, and CLI admission; `src/vaultspec_rag/tests/test_job_contracts_persistence.py, src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py, src/vaultspec_rag/tests/test_cli_index.py`.

### Phase `W03.P13` - finish the canonical reader cutover

Move the remaining runtime consumers directly to canonical proof in one cohesive implementation pass, fail old or missing proof closed, and remove consumer-side sidecar authority without adding a selector or fallback.

- [x] `W03.P13.S71` - Cut every remaining breadth, integrity, donor, survey, reclamation, archive, restore, cleanup, and search-fence consumer directly to canonical committed proof, deleting sidecar reads and failing missing or obsolete proof closed; `src/vaultspec_rag/_index_breadth.py, src/vaultspec_rag/_index_integrity.py, src/vaultspec_rag/indexer/_donor_candidates.py, src/vaultspec_rag/generation_survey.py, src/vaultspec_rag/storage_survey_ops.py, src/vaultspec_rag/storage_reclamation.py, src/vaultspec_rag/storage_manifest.py, src/vaultspec_rag/api.py, src/vaultspec_rag/cli/_search.py, src/vaultspec_rag/_public_search.py, src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/tests`.

## Wave `W02` - cut over canonical proof producers

Translate code, document, and vault outcomes into the sole canonical proof authority and delete sidecar writers and models. This Wave depends on Waves 1 and 3.

### Phase `W02.P14` - replace the incremental publication hot paths

Wire the existing proof and receipt foundation into the real scoped publication paths, then remove every corpus-wide manifest, scan, and sidecar implementation from normal publication.

- [x] `W02.P14.S72` - Replace shared scoped finalization, route reconciliation, and stat evidence with receipt-backed changed-key operations so the common publication path performs no corpus-wide work; `src/vaultspec_rag/indexer/_checkpoint_common.py, src/vaultspec_rag/indexer/_run_checkpoint.py, src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_run_ledger_finalization.py, src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/indexer/_stat_gate.py`.
- [x] `W02.P14.S73` - Switch code publication to canonical receipts and exact deltas, remove full collection breadth scans and complete metadata reconstruction, and delete the code sidecar implementation and imports; `src/vaultspec_rag/indexer/_incremental_commit.py, src/vaultspec_rag/indexer/_consumer_pipeline.py, src/vaultspec_rag/indexer/_generation_lifecycle.py, src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_code_meta.py, src/vaultspec_rag/store_catalog.py`.
- [x] `W02.P14.S74` - Switch document publication to canonical receipts and exact deltas, remove complete manifest reconstruction, and delete the document sidecar implementation and imports; `src/vaultspec_rag/indexer/_document_checkpoint.py, src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_document_meta.py`.
- [x] `W02.P14.S75` - Switch vault publication to the canonical receipt lifecycle and exact deltas, remove stored-identity scans and complete prior-map reconstruction, and delete the vault sidecar implementation and imports; `src/vaultspec_rag/indexer/_vault_incremental.py, src/vaultspec_rag/indexer/_vault_checkpoint.py, src/vaultspec_rag/indexer/_vault_indexer.py, src/vaultspec_rag/indexer/_vault_meta.py`.
- [x] `W02.P14.S76` - Delete obsolete manifest ancestry, full-manifest iterators, sidecar models and exports, fallback or migration code, and any remaining normal-publication full-scan call sites; `src/vaultspec_rag/indexer, src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.

## Wave `W04` - prove issue 469 is closed

Verify the completed implementation against the issue's observable cost, correctness, recovery, and legacy-removal criteria after engineering is finished.

### Phase `W04.P15` - demonstrate the issue is closed

After implementation is complete, measure operation growth, exercise recovery and source behavior, run the repository gates once, and review the finished change against issue 469.

- [ ] `W04.P15.S77` - Prove the finished implementation meets issue 469 with source integration and crash-recovery coverage, deterministic operation-count scaling, a large-parent single-change benchmark, one full repository gate run, and one final code review; `src/vaultspec_rag/tests, src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`.

## Parallelization

The three source cutovers may be developed independently after the shared publication seam
is stable, provided their file ownership does not overlap. Reader and producer changes are
development states within one unreleased pull request; no intermediate state is a release
boundary.

Implementation uses normal engineering loops: inspect the seam, change the code, run the
smallest useful tests, and keep moving. Per-slice audit documents, independent reviews,
mutation exercises, and complete gate runs are explicitly out of scope.

## Verification

- For a fixed one-path delta, proof-row mutations, backend point operations, and retained-ID
  work remain bounded while the parent corpus grows.
- Normal scoped code, document, and vault publication performs no collection-wide identity
  scan, parent-manifest copy, complete metadata serialization, full route sweep, or complete
  stat-evidence rewrite.
- Add, modify, delete, rename, empty, ignored or rejected, and no-op outcomes update exact
  breadth correctly for all three sources.
- Storage mutation intent is durable before the store call; acknowledged work is replayable;
  proof commits before generation or served-pointer publication.
- Missing, obsolete, incompatible, or corrupt proof fails closed, and only explicit rebuild
  publication creates replacement proof. Audit remains non-seeding.
- The source tree has no sidecar authority, migration or fallback reader, selector, shim,
  alias, deprecated compatibility export, eager parent-manifest copy, or normal-path full
  scan.
- After implementation is complete, run focused source and recovery integration suites,
  deterministic operation-count assertions, one large-parent benchmark, formatting, lint,
  strict types, the full repository gates, Vaultspec checks, and one final code review.
