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
body_hash: 'sha256:d5849b96b775af8ba895c41ddb7d2f66d71c9636e957db28d8f9f3b0e7917da4'
---

# `incremental-publication-cost` plan

Replace corpus-wide publication scans and manifest rewrites with exact ledger-backed
deltas, recoverable receipts, and separately authorized verification.

## Description

Implement the accepted normalized publication-proof model in four ordered Waves. Wave 1
establishes proof identity, exact delta algebra, normalized ledger state, and recoverable
finalization. Wave 2 routes code, document, and vault publication through that shared owner
without copying parent manifests or scanning collection breadth. Wave 3 migrates proof
consumers and keeps full backend reconciliation behind explicit authority. Wave 4 adds
deterministic proportionality guards, telemetry, fault injection, and performance evidence.
Existing explicit-reindex authority, source isolation, generation accounting, and
pointer-last replacement publication remain unchanged.

## Steps

## Wave `W01` - establish the durable proof authority

Deliver the normalized proof contract and durable receipt state machine required by every source adapter. All later Waves depend on it.

### Phase `W01.P01` - define proof values and exact delta algebra

Provide source-neutral immutable values for proof identity, path outcomes, aggregates, receipt states, provenance, and typed unverifiable outcomes.

- [ ] `W01.P01.S01` - Define publication proof identities, path deltas, aggregate arithmetic, receipt states, provenance, and typed failures; `src/vaultspec_rag/indexer/_publication_proof.py`.
- [ ] `W01.P01.S02` - Prove add, modify, delete, rename, empty, ignored, rejected, and no-op delta behavior; `src/vaultspec_rag/tests/test_publication_proof.py`.

### Phase `W01.P02` - persist normalized proofs and receipts

Give the run ledger normalized manifest rows, exact retained-point relations, aggregates, revisions, and idempotent prepare, apply, and commit operations without copying a parent manifest.

- [ ] `W01.P02.S03` - Extend ledger value and schema contracts for proof revisions, rows, aggregates, receipts, and provenance; `src/vaultspec_rag/indexer/_run_ledger_models.py`.
- [ ] `W01.P02.S04` - Create and migrate proof tables and replace eager parent-manifest copying with ancestry references; `src/vaultspec_rag/indexer/_run_ledger_runtime.py`.
- [ ] `W01.P02.S05` - Implement transactional proof reads, exact path updates, aggregate updates, receipt transitions, and ancestry validation; `src/vaultspec_rag/indexer/_run_ledger_publication.py`.
- [ ] `W01.P02.S06` - Preserve retained-point evidence and deterministic mutation identities across receipt replay; `src/vaultspec_rag/indexer/_run_ledger_commits.py`.
- [ ] `W01.P02.S07` - Prove schema migration, ancestry, aggregate deltas, mismatch refusal, receipt replay, and proof atomicity; `src/vaultspec_rag/tests/test_index_run_ledger.py`.
- [ ] `W01.P02.S08` - Prove concurrent readers observe committed proof revisions and interrupted writers cannot certify partial state; `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`.

### Phase `W01.P03` - own recoverable publication finalization

Move proof preparation, confirmation, commit, and restart recovery into the shared finalization owner while retaining generation-last and pointer-last ordering.

- [ ] `W01.P03.S09` - Replace sidecar-oriented metadata transitions with receipt-backed proof preparation, confirmation, commit, and recovery; `src/vaultspec_rag/indexer/_checkpoint_common.py`.
- [ ] `W01.P03.S10` - Enforce proof-before-generation finalization and retain proof ancestry during compaction; `src/vaultspec_rag/indexer/_run_ledger_finalization.py`.
- [ ] `W01.P03.S11` - Prove shared transition ownership, parent mismatch refusal, and generation publication ordering; `src/vaultspec_rag/tests/test_checkpoint_common.py`.
- [ ] `W01.P03.S12` - Prove restart convergence from every prepared, applied, confirmed, committed, and generation-lagging receipt state; `src/vaultspec_rag/tests/test_run_checkpoint.py`.

## Wave `W02` - adopt exact deltas in each source adapter

Translate code, document, and vault outcomes into the shared proof authority while preserving source-specific classification and payload rules. This Wave depends on Wave 1.

### Phase `W02.P04` - migrate code publication

Remove full code metadata cloning and publication-time collection breadth scans from scoped code indexing.

- [ ] `W02.P04.S13` - Prepare deterministic code replacement receipts and confirm idempotent storage mutations before proof commit; `src/vaultspec_rag/indexer/_incremental_commit.py`.
- [ ] `W02.P04.S14` - Publish code aggregates without collection-wide counts while retaining pointer-last replacement ordering; `src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [ ] `W02.P04.S15` - Emit exact changed-path outcomes instead of cloning and rewriting the complete prior metadata map; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P04.S16` - Retain code sidecars only as bounded legacy migration input and remove authoritative writes; `src/vaultspec_rag/indexer/_code_meta.py`.
- [ ] `W02.P04.S17` - Prove scoped code add, modify, delete, rename, empty, ignored, no-op, and interrupted publication; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.

### Phase `W02.P05` - migrate document publication

Replace full document manifest reconstruction with exact per-document proof updates.

- [ ] `W02.P05.S18` - Translate document slice and deletion outcomes into shared proof deltas and receipts; `src/vaultspec_rag/indexer/_document_checkpoint.py`.
- [ ] `W02.P05.S19` - Consume canonical proof state for scoped document decisions without materializing a complete manifest; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W02.P05.S20` - Retain document sidecars only for legacy migration and remove authoritative full-manifest publication; `src/vaultspec_rag/indexer/_document_meta.py`.
- [ ] `W02.P05.S21` - Prove document checkpoint delta translation and restart recovery; `src/vaultspec_rag/tests/test_document_checkpoint.py`.
- [ ] `W02.P05.S22` - Prove document add, modify, delete, rename, empty, ignored, no-op, and interrupted publication; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.

### Phase `W02.P06` - migrate vault publication

Remove complete prior-map copying and full stored-identity breadth scans from scoped vault indexing.

- [ ] `W02.P06.S23` - Emit exact vault body, metadata-only, deletion, rejection, rename, and no-op proof deltas; `src/vaultspec_rag/indexer/_vault_incremental.py`.
- [ ] `W02.P06.S24` - Commit vault proof breadth without scanning all stored identities or rewriting a complete hash map; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `W02.P06.S25` - Retain vault metadata only as bounded legacy migration input and remove authoritative fields; `src/vaultspec_rag/indexer/_vault_meta.py`.
- [ ] `W02.P06.S26` - Prove true incremental vault publication and metadata-only updates against canonical proof state; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W02.P06.S27` - Prove exact vault breadth across deletion, interruption, and restart; `src/vaultspec_rag/tests/integration/test_vault_breadth_publication.py`.

## Wave `W03` - migrate proof consumers and exceptional verification

Make the ledger the sole proof reader and keep full backend scans behind explicit verification authority. This Wave depends on Wave 2.

### Phase `W03.P07` - replace legacy completeness readers

Route every production consumer to canonical proof state without maintaining another authoritative manifest.

- [ ] `W03.P07.S28` - Read code and vault breadth from committed proof aggregates with typed missing or incompatible evidence; `src/vaultspec_rag/_index_breadth.py`.
- [ ] `W03.P07.S29` - Compare backend contents with canonical proof only during explicitly authorized integrity verification; `src/vaultspec_rag/_index_integrity.py`.
- [ ] `W03.P07.S30` - Select document donors from compatible proof identity and retained-point evidence; `src/vaultspec_rag/indexer/_donor_candidates.py`.
- [ ] `W03.P07.S31` - Report canonical proof state in storage surveys and classify sidecars as migration artifacts; `src/vaultspec_rag/storage_survey_ops.py`.
- [ ] `W03.P07.S32` - Base safe metadata reclamation on canonical proof ownership and revision state; `src/vaultspec_rag/storage_reclamation.py`.
- [ ] `W03.P07.S33` - Route index cleanup through proof lifecycle ownership instead of document-sidecar authority; `src/vaultspec_rag/api.py`.
- [ ] `W03.P07.S34` - Prove breadth readers distinguish missing, incompatible, delta-derived, and fully verified proof; `src/vaultspec_rag/tests/test_indexer_unit.py`.
- [ ] `W03.P07.S35` - Prove integrity verification detects missing, extra, foreign, incompatible, and partial backend state; `src/vaultspec_rag/tests/test_index_integrity.py`.
- [ ] `W03.P07.S36` - Prove donor selection refuses incompatible or unverifiable proof ancestry; `src/vaultspec_rag/tests/test_donor_candidates.py`.

### Phase `W03.P08` - authorize migration and full verification

Ensure legacy evidence can seed canonical proof only through an explicit and separately measured operation.

- [ ] `W03.P08.S37` - Encode explicit rebuild and verification authority in the canonical run operation; `src/vaultspec_rag/indexer/_run_ledger_models.py`.
- [ ] `W03.P08.S38` - Route service rebuild and verification requests through explicit authority without widening scoped publication; `src/vaultspec_rag/server/_routes_reindex.py`.
- [ ] `W03.P08.S39` - Route CLI rebuild and verification requests through explicit authority without granting scoped scan permission; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W03.P08.S40` - Prove legacy, missing-ancestry, schema-drift, and corrupt-receipt cases require explicit authority; `src/vaultspec_rag/tests/test_document_index_escalation.py`.
- [ ] `W03.P08.S41` - Prove replacement verification commits proof before moving the served pointer; `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.
- [ ] `W03.P08.S52` - Carry explicit rebuild and verification authority through persisted job contracts; `src/vaultspec_rag/job_models.py`.

## Wave `W04` - prove proportionality and operational visibility

Add deterministic regression guards, fault injection, telemetry, and end-to-end verification. This Wave depends on Waves 1 through 3.

### Phase `W04.P09` - expose publication cost telemetry

Report changed identities, proof rows, backend point operations, phase timings, and full-verification breadth through stable result surfaces.

- [ ] `W04.P09.S42` - Add publication operation counts and phase timings to indexing results; `src/vaultspec_rag/indexer/_vault_prep.py`.
- [ ] `W04.P09.S43` - Project publication and verification telemetry into the stable CLI result row; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W04.P09.S44` - Preserve publication telemetry through service job dispatch results; `src/vaultspec_rag/job_dispatch.py`.
- [ ] `W04.P09.S45` - Prove stable CLI output for incremental and full-verification cost fields; `src/vaultspec_rag/tests/test_cli_index.py`.
- [ ] `W04.P09.S46` - Prove service indexing results retain source-scoped publication telemetry; `src/vaultspec_rag/tests/integration/test_index_reuse_daemon_path.py`.

### Phase `W04.P10` - install architectural and cost guards

Make corpus-wide work in scoped publication fail deterministically and demonstrate that the guards can fail.

- [ ] `W04.P10.S47` - Guard single proof ownership and forbid scoped calls to full-scan publication APIs; `src/vaultspec_rag/tests/test_process_probe_ownership_guards.py`.
- [ ] `W04.P10.S48` - Prove scoped code operation counts remain proportional to changed identities and points; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [ ] `W04.P10.S49` - Prove scoped document operation counts remain proportional to changed identities and retained points; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.
- [ ] `W04.P10.S50` - Prove scoped vault operation counts remain proportional to changed identities and points; `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`.
- [ ] `W04.P10.S51` - Add a large-parent single-path benchmark for writer-lease and publication-cost regression; `src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`.

## Parallelization

Waves execute in order. Within Wave 1, P01 precedes P02 and P03 depends on both. After the
shared proof and checkpoint contracts land, P04, P05, and P06 may execute in parallel with
exclusive ownership of their source adapters and integration tests. In Wave 3, independent
consumer migrations in P07 may execute concurrently after the canonical reader stabilizes;
P08 follows P07. In Wave 4, telemetry propagation and source-specific proportionality tests
may run in parallel after the result shape is fixed. Shared seams
`_checkpoint_common.py`, `_run_ledger_runtime.py`, `_index_breadth.py`, and
`_vault_prep.py` are never edited concurrently.

## Verification

- Unit gates pass for proof algebra, ledger persistence and migration, checkpoint
  transitions, receipt recovery, and concurrency.
- Code, document, and vault integration gates cover add, modify, delete, rename, empty,
  ignored or rejected, no-op, interruption, replay, and rebuild behavior.
- Scoped publication performs no collection-wide scroll, distinct-identity scan,
  parent-manifest copy, or complete sidecar serialization.
- Operation counts remain proportional to changed identities and point mutations as total
  corpus size grows; large-index elapsed budgets cover writer-lease duration.
- Full verification is reachable only through explicit rebuild, migration, recovery, or
  audit authority and reports scanned breadth separately.
- Replacement proof commits before the served pointer advances, and failed replacement
  leaves the prior generation served.
- Legacy sidecars are bounded migration input only and are never dual-written as an
  independent authority.
- Backend, collection, generation, schema, source, membership, content, and policy mismatch
  cases fail closed with typed outcomes.
- Every guard and negative test is mutation-proven red on its intended assertion and green
  after restoration, with both directions recorded in the test.
- Formatting, lint, strict type checks, targeted unit and integration suites, benchmark
  gates, `vaultspec-core vault plan check`, and `vaultspec-core vault check all` pass
  explicitly before closeout.
- A formal `vaultspec-code-review` finds no blocking safety, intent, or quality defects.
