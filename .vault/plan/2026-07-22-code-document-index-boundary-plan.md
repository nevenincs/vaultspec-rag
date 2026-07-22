---
tags:
  - '#plan'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-21-code-document-index-boundary-adr]]'
  - '[[2026-07-21-code-document-index-boundary-research]]'
  - '[[2026-07-21-code-document-index-boundary-reference]]'
  - '[[2026-07-21-large-index-resilience-plan]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `code-document-index-boundary` plan

## Description

Restore an explicit, caller-configured boundary between source code and documents without
assigning meaning to repository layout. Use one path-agnostic admission policy and resolve one
immutable policy snapshot per operation. Fail closed when routing is invalid or unmigrated.
Give documents independent storage, indexing, search, lifecycle, recovery, and resource
profiles while preserving preprocessing fidelity and cache identity.

The related resilience plan owns the shared generation ledger. Its open ledger and restart
rows now require content kind, policy identity, explicit per-file convergence state, and
independently publishable generations. These requirements apply from their first
implementation. This plan consumes that contract after the resilience restart gate and
doesn't create a competing checkpoint system.

Retain the 250,872-chunk representative source-code workload gate. Evaluate documents against
a separate bounded document support profile. Public adapters include the application programming
interface (API), command-line interface (CLI), Hypertext Transfer Protocol (HTTP) service, and
Model Context Protocol (MCP) tools. Resource gates cover central processing unit (CPU) work,
graphics processing unit (GPU) work, resident set size (RSS), and Compute Unified Device
Architecture (CUDA) memory.

## Steps

## Wave `W01` - policy authority and admission parity

Establish one caller-configured content policy and one immutable operation snapshot before any storage or execution path classifies input. Later waves depend on these contracts.

### Phase `W01.P01` - typed policy and fail-closed configuration

Define generic content ownership, routing, migration, and fingerprint contracts without deriving membership from parser capability or repository layout.

- [x] `W01.P01.S01` - Define closed content-kind, admission-disposition, stable-reason, and source-profile-version types; `src/vaultspec_rag/indexer/_content_policy.py`.
- [x] `W01.P01.S02` - Define ordered root routing rules independently from optional preprocessing transforms; `src/vaultspec_rag/config.py, src/vaultspec_rag/indexer/_content_policy.py`.
- [x] `W01.P01.S03` - Upgrade preprocessing configuration to require a target and explicit extractor version under a versioned schema; `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `W01.P01.S04` - Reject legacy targetless, unknown-target, and conflicting routing policies before mutable index resources are opened; `src/vaultspec_rag/indexer/_preprocess_config.py, src/vaultspec_rag/indexer/_content_policy.py, src/vaultspec_rag/_job_errors.py`.
- [x] `W01.P01.S05` - Compile ignore precedence, explicit ownership, source-profile admission, and parser selection into one deterministic classifier; `src/vaultspec_rag/indexer/_content_policy.py, src/vaultspec_rag/indexer/_ignore_specs.py, src/vaultspec_rag/indexer/_chunking.py`.
- [x] `W01.P01.S06` - Resolve one immutable policy snapshot containing routing, preprocessing, decoding, execution mode, and normalized fingerprints; `src/vaultspec_rag/indexer/_resolved_policy.py, src/vaultspec_rag/indexer/_config_epoch.py`.
- [x] `W01.P01.S37` - Define indexed, policy-rejected, retryable-extraction, terminal-extraction, decode-failed, and chunk-failed file states; `src/vaultspec_rag/indexer/_file_state.py, src/vaultspec_rag/_job_errors.py`.
- [x] `W01.P01.S47` - Derive per-kind membership and content signatures from source profile, ordered routes, targets, ignores, schema, and extractor semantics; `src/vaultspec_rag/indexer/_config_epoch.py, src/vaultspec_rag/indexer/_resolved_policy.py`.
- [x] `W01.P01.S07` - Verify real configuration loading, route ordering, one-owner enforcement, and mutation-free migration refusal; `src/vaultspec_rag/tests/test_content_policy.py, src/vaultspec_rag/tests/test_preprocess_config.py`.
- [x] `W01.P01.S88` - Gate index and job entry points on a valid resolved policy before acquiring store, ledger, cache, writer, or GPU mutation authority; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/jobs.py`.
- [x] `W01.P01.S89` - Verify invalid routing leaves real collections, sidecars, ledger rows, and caches unchanged; `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`.

### Phase `W01.P02` - shared discovery and preflight

Make full, scoped, watcher, API, CLI, and service discovery consume the same policy snapshot while preserving the public path-list compatibility projection.

- [x] `W01.P02.S08` - Separate conventional source admission from the parser and chunker capability registry; `src/vaultspec_rag/indexer/_chunking.py, src/vaultspec_rag/indexer/_content_policy.py`.
- [x] `W01.P02.S09` - Route full and unscoped discovery through the shared classifier and resolved policy snapshot; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P02.S10` - Route scoped discovery through the shared classifier and resolved policy snapshot; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P02.S11` - Add a bounded structured scan result and retain the public path-list scan as its compatibility projection; `src/vaultspec_rag/api.py, src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S12` - Make CLI dry-run apply the same preprocessing mode and return the structured admission summary; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W01.P02.S13` - Make resident-service preflight consume the structured scan without independently reloading configuration; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/server/_routes.py`.
- [x] `W01.P02.S14` - Verify full, scoped, API, CLI, and service admission parity against one real temporary repository; `src/vaultspec_rag/tests/integration/test_content_admission.py`.
- [ ] `W01.P02.S90` - Thread the exact resolved snapshot through worker execution, epochs, ledger signatures, and metadata publication without a second configuration load; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_preprocess_glue.py, src/vaultspec_rag/indexer/_chunk_worker.py`.
- [ ] `W01.P02.S91` - Verify an on-disk configuration edit during real extraction cannot change the active operation fingerprint or publication identity; `src/vaultspec_rag/tests/integration/test_policy_snapshot.py`.
- [x] `W01.P02.S92` - Route ordinary added and modified watcher paths through the shared disposition and active policy snapshot; `src/vaultspec_rag/watcher.py`.
- [x] `W01.P02.S93` - Verify watcher classification matches full and scoped discovery for ordinary real file events; `src/vaultspec_rag/tests/integration/test_watcher_content_admission.py`.
- [ ] `W01.P02.S94` - Retain resolved routing when preprocessing execution is disabled and mark affected work stale without deletion or reclassification; `src/vaultspec_rag/indexer/_preprocess_config.py, src/vaultspec_rag/indexer/_preprocess_glue.py, src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S95` - Verify the preprocessing kill switch suppresses real extractor execution while preserving ownership and stored points; `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.

## Wave `W02` - document storage and ingestion isolation

Introduce independently owned document models, storage, lifecycle, and ingestion paths. Enforce isolation through separate models, collections, and lifecycle operations, not only result labels.

### Phase `W02.P03` - document models and storage contract

Create document-native identity, payload, collection, metadata, lock, lifecycle, and administration contracts while preserving existing source point identities.

- [x] `W02.P03.S15` - Define document chunk, locator, metadata, payload, and result models distinct from source chunks; `src/vaultspec_rag/_store_models.py, src/vaultspec_rag/search/_models.py`.
- [ ] `W02.P03.S16` - Implement collection-local document point identities from normalized source, native locator or unit ordinal, and content fingerprint; `src/vaultspec_rag/indexer/_document_identity.py`.
- [ ] `W02.P03.S17` - Add the document collection, payload indexes, schema-version contract, descriptor entry, and direct-consumer compatibility behavior; `src/vaultspec_rag/store_schema.py`.
- [ ] `W02.P03.S18` - Add document collection locks, upsert, delete, scroll, and count operations; `src/vaultspec_rag/store.py, src/vaultspec_rag/_store_locks.py`.
- [ ] `W02.P03.S19` - Add independent document metadata publication and compatibility markers; `src/vaultspec_rag/indexer/_document_meta.py`.
- [ ] `W02.P03.S20` - Add targeted document clean semantics without evicting code state or unrelated extraction cache entries; `src/vaultspec_rag/api.py, src/vaultspec_rag/store.py`.
- [ ] `W02.P03.S21` - Add the document collection to storage manifest recording and schema compatibility; `src/vaultspec_rag/storage_manifest.py, src/vaultspec_rag/store_schema.py`.
- [ ] `W02.P03.S22` - Verify document identities, schema, locks, and lifecycle against real local and server Qdrant stores; `src/vaultspec_rag/tests/integration/test_document_store.py`.
- [ ] `W02.P03.S96` - Include document collections and bounded counts in storage survey output; `src/vaultspec_rag/storage_survey.py`.
- [ ] `W02.P03.S97` - Include document collections and metadata in snapshot manifests; `src/vaultspec_rag/storage_manifest.py, src/vaultspec_rag/storage_ops.py`.
- [ ] `W02.P03.S98` - Migrate document collections idempotently between local and resident-service storage; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W02.P03.S99` - Include document collections in prefix pruning, debris classification, and storage maintenance routes; `src/vaultspec_rag/storage_ops.py, src/vaultspec_rag/server/_routes_storage.py`.
- [ ] `W02.P03.S100` - Verify older and newer storage descriptors fail or migrate according to the direct-consumer compatibility contract; `src/vaultspec_rag/tests/integration/test_document_store.py`.
- [ ] `W02.P03.S121` - Verify document collection counts appear in real storage survey output; `src/vaultspec_rag/tests/integration/test_document_store.py`.
- [ ] `W02.P03.S122` - Verify document collection and metadata appear in a real snapshot manifest; `src/vaultspec_rag/tests/integration/test_document_store.py`.
- [ ] `W02.P03.S123` - Verify real local-to-service document migration is idempotent; `src/vaultspec_rag/tests/integration/test_service_storage_migration.py`.
- [ ] `W02.P03.S124` - Verify document prefix pruning, debris classification, and maintenance routes against real storage; `src/vaultspec_rag/tests/integration/test_service_storage_migration.py`.

### Phase `W02.P04` - kind-aware ingestion paths

Route admitted source and document units into their own production models and stores while preserving metadata and explicit per-domain outcomes.

- [ ] `W02.P04.S23` - Split worker output into source and document chunk result types without overloading `CodeChunk`; `src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/_store_models.py`.
- [ ] `W02.P04.S24` - Preserve title, section, anchor, locator, document metadata, unit metadata, and extractor identity on document chunks; `src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/_store_models.py`.
- [ ] `W02.P04.S25` - Dispatch bounded streaming batches to the collection selected by each admission disposition; `src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P04.S26` - Implement full document indexing behind one service-domain entry point; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/api.py`.
- [ ] `W02.P04.S27` - Return explicit per-domain outcomes from all indexing without hiding a partial failure; `src/vaultspec_rag/api.py, src/vaultspec_rag/jobs.py`.
- [ ] `W02.P04.S28` - Verify source and extracted units reach only their assigned collections through the real embedding and storage path; `src/vaultspec_rag/tests/integration/test_document_indexing.py, src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [ ] `W02.P04.S101` - Implement unscoped incremental document indexing behind the service-domain entry point; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/api.py`.
- [ ] `W02.P04.S102` - Implement scoped incremental document indexing behind the service-domain entry point; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/api.py`.
- [ ] `W02.P04.S103` - Register document indexer construction, counts, close lifecycle, and watcher injection in managed project slots; `src/vaultspec_rag/service.py, src/vaultspec_rag/registry.py, src/vaultspec_rag/server/_watcher.py`.
- [ ] `W02.P04.S104` - Ingest explicitly routed decodable raw documents without launching an extractor; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_chunk_worker.py`.
- [ ] `W02.P04.S105` - Verify raw and extracted document routes remain document-owned through real full and incremental indexing; `src/vaultspec_rag/tests/integration/test_document_indexing.py`.

## Wave `W03` - faithful bounded preprocessing and convergence

Harden extraction identity, metadata, caching, failure state, and resource accounting after storage isolation exists. Require durable, explicit outcomes before restart-safe reconciliation.

### Phase `W03.P05` - invocation and cache fidelity

Deliver every semantics-bearing extractor input, bind output to the host-owned source, and prevent cache aliasing across paths, options, versions, or content domains.

- [ ] `W03.P05.S29` - Define a versioned extractor invocation envelope with canonical source identity, normalized options, configured version, target, and mode; `src/vaultspec_rag/indexer/_preprocess_schema.py, src/vaultspec_rag/indexer/_preprocess_config.py`.
- [ ] `W03.P05.S30` - Deliver the invocation envelope to command extractors without shell-specific argument reconstruction; `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [ ] `W03.P05.S31` - Deliver the invocation envelope to entry-point extractors with the same contract as command execution; `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [ ] `W03.P05.S32` - Reject emitted source redirection and validate bounded document and unit metadata; `src/vaultspec_rag/indexer/_preprocess_schema.py, src/vaultspec_rag/indexer/_chunk_worker.py`.
- [ ] `W03.P05.S33` - Key extraction cache entries by source path, source hash, output schema, and canonical execution fingerprint; `src/vaultspec_rag/indexer/_preprocess_cache.py, src/vaultspec_rag/indexer/_chunk_worker.py`.
- [ ] `W03.P05.S34` - Permit cross-path cache reuse only for extractors that explicitly declare path independence; `src/vaultspec_rag/indexer/_preprocess_config.py, src/vaultspec_rag/indexer/_preprocess_cache.py`.
- [ ] `W03.P05.S35` - Partition extraction cache lifecycle from code and document collection cleanup; `src/vaultspec_rag/indexer/_preprocess_cache.py, src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W03.P05.S36` - Verify options, versions, source binding, metadata retention, and path-dependent cache behavior with real extractor processes; `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [ ] `W03.P05.S106` - Render targets, extractor versions, path-independence, schema migration, and disabled execution through preprocess list, check, and status; `src/vaultspec_rag/cli/_preprocess.py`.

### Phase `W03.P06` - explicit failure outcomes and resource bounds

Represent unsuccessful files as unresolved work and apply enforceable source, output, chunk, queue, host-memory, and device-memory limits to document execution.

- [ ] `W03.P06.S38` - Apply the source decoder only after code admission and bypass it for extractor-owned document input; `src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/indexer/_content_policy.py`.
- [ ] `W03.P06.S39` - Keep skip, fail, and passthrough outcomes in their declared kind and require same-kind raw admission for passthrough; `src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [ ] `W03.P06.S40` - Publish hashes as converged metadata only for indexed or stable policy-rejected files; `src/vaultspec_rag/indexer/_code_meta.py, src/vaultspec_rag/indexer/_document_meta.py`.
- [ ] `W03.P06.S41` - Keep retryable extraction as a service-owned obligation with bounded per-kind backoff and circuit state; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/watcher_retry.py`.
- [ ] `W03.P06.S42` - Stream source hashing and enforce profile and per-rule source-byte ceilings before extraction; `src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/indexer/_preprocess_config.py`.
- [ ] `W03.P06.S43` - Measure emitted encoded bytes and enforce aggregate output, chunk, payload, and weighted-queue ceilings; `src/vaultspec_rag/indexer/_preprocess_runner.py, src/vaultspec_rag/indexer/_streaming.py`.
- [ ] `W03.P06.S44` - Make batch extraction, subprocess output, timeout, no-progress, and cancellation bounded and interruptible; `src/vaultspec_rag/indexer/_preprocess_runner.py, src/vaultspec_rag/indexer/_run_policy.py`.
- [ ] `W03.P06.S45` - Share the index limiter, writer authority, GPU consumer, and memory policy while isolating per-kind operational state; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/indexer/_streaming.py`.
- [ ] `W03.P06.S46` - Verify failure visibility, decoder isolation, retry behavior, resource ceilings, and zero extractor launches for code-only jobs; `src/vaultspec_rag/tests/integration/test_document_execution.py, src/vaultspec_rag/tests/integration/test_service_jobs.py`.
- [ ] `W03.P06.S107` - Define and enforce a named document support profile at service job admission before GPU work; `src/vaultspec_rag/index_profiles.py, src/vaultspec_rag/jobs.py`.

## Wave `W04` - per-kind generations and route migration

A generation-metadata sidecar records the last published file membership. Consume the related resilience ledger and add destination-first recovery for target changes, incomplete publication, and watcher deletions.

### Phase `W04.P07` - generation identity and publication

Bind resolved policy identity and explicit file outcomes into independent code and document generations after the related resilience restart gate is complete.

- [ ] `W04.P07.S48` - Validate that completed source indexing exposes the policy, file-state, and publication evidence required by route migration; `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`.
- [ ] `W04.P07.S49` - Bind admitted kind and explicit file outcome to the shared generation-ledger API in document indexing; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/indexer/_run_ledger.py`.
- [ ] `W04.P07.S50` - Certify per-kind publication only after ingestion, deletion, metadata, schema, and ledger finalization complete; `src/vaultspec_rag/indexer/_code_meta.py, src/vaultspec_rag/indexer/_document_meta.py`.
- [ ] `W04.P07.S51` - Verify independent per-kind signatures, bounded replay, and publication completeness through the shared production generation ledger; `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`.

### Phase `W04.P08` - destination-first reconciliation and watcher recovery

Recover legacy and interrupted state by freshly classifying bounded store rows, publishing destinations before deleting origins, and retaining prior ownership for missing paths.

- [ ] `W04.P08.S52` - Survey legacy points in bounded pages and classify current ownership without trusting generation-metadata sidecars alone; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/store.py`.
- [ ] `W04.P08.S53` - Upsert and checkpoint freshly generated destination points before authorizing origin cleanup; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W04.P08.S54` - Delete and checkpoint origin points only after destination publication is durable; `src/vaultspec_rag/indexer/_route_migration.py, src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W04.P08.S55` - Resume target flips idempotently from every durable migration boundary; `src/vaultspec_rag/indexer/_route_migration.py`.
- [ ] `W04.P08.S56` - Recover stored segments with a missing generation-metadata sidecar without dropping confirmed work; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W04.P08.S57` - Recover a partial replacement generation with a stale generation-metadata sidecar without certifying incomplete storage; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_document_indexer.py`.
- [ ] `W04.P08.S58` - Use prior ledger ownership for deleted paths and schedule every affected kind after policy control events; `src/vaultspec_rag/watcher.py`.
- [ ] `W04.P08.S59` - Keep per-kind watcher pending, retry, and circuit state under shared writer and GPU authority; `src/vaultspec_rag/watcher.py, src/vaultspec_rag/watcher_retry.py`.
- [ ] `W04.P08.S60` - Verify missing and stale generation-metadata sidecars, interrupted target flips, deletions, and policy-change recovery with real stores and watcher events; `src/vaultspec_rag/tests/integration/test_content_route_migration.py, src/vaultspec_rag/tests/integration/test_document_watcher.py`.

## Wave `W05` - exhaustive public lifecycle and search

Expose document ownership through one canonical public type, independent lifecycle and query behavior, and explicit three-domain combined outcomes without adapter fallthrough or reinterpretation of existing aliases.

### Phase `W05.P09` - service-owned query semantics

Define strict source parsing, document-native results, and explicit candidate allocation, filtering, reranking, and final selection across vault, code, and document storage.

- [ ] `W05.P09.S61` - Define a closed public source-type parser with canonical document and structured unknown-type errors; `src/vaultspec_rag/_source_types.py`.
- [ ] `W05.P09.S62` - Retrieve document candidates from the document collection with document-specific filters and diagnostics; `src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/_store_search.py`.
- [ ] `W05.P09.S63` - Shape document hits with document labels, locators, metadata, and source identities; `src/vaultspec_rag/search/_models.py, src/vaultspec_rag/search/_result_shaping.py`.
- [ ] `W05.P09.S64` - Allocate candidates explicitly across vault, code, and document collections for combined search; `src/vaultspec_rag/search/_searcher.py`.
- [ ] `W05.P09.S65` - Apply content-kind-aware filtering and reranking before deterministic combined top-k selection; `src/vaultspec_rag/search/_validation.py, src/vaultspec_rag/search/_rerank.py, src/vaultspec_rag/search/_searcher.py`.
- [ ] `W05.P09.S66` - Add document and combined indexing facades with explicit per-domain partial outcomes; `src/vaultspec_rag/api.py`.
- [ ] `W05.P09.S67` - Verify independent and combined search against real stored content, correct labels, real reranker inputs, and deterministic top-k; `src/vaultspec_rag/tests/integration/test_document_search.py`.
- [ ] `W05.P09.S108` - Add document and combined search facades with explicit filters, diagnostics, and per-domain partial outcomes; `src/vaultspec_rag/api.py`.

### Phase `W05.P10` - lifecycle and adapter exhaustiveness

Carry the closed source type and canonical service outcomes through clean, status, jobs, HTTP, service transport, CLI, and MCP without duplicating classification rules.

- [ ] `W05.P10.S68` - Add independent document counts and document status; `src/vaultspec_rag/api.py, src/vaultspec_rag/service.py, src/vaultspec_rag/cli/_status.py`.
- [ ] `W05.P10.S69` - Add document job sources, per-domain generation state, combined outcomes, and readiness snapshots; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W05.P10.S70` - Add exhaustive document and combined HTTP search routes; `src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_routes.py`.
- [ ] `W05.P10.S71` - Add document and combined envelopes to resident-service transport without permissive fallback; `src/vaultspec_rag/serviceclient/_transport.py`.
- [ ] `W05.P10.S72` - Add canonical document and combined index and dry-run CLI behavior; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W05.P10.S73` - Add document and combined search tools with strict source parsing; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W05.P10.S74` - Verify valid and unknown source types and per-domain partial outcomes through the in-process API; `src/vaultspec_rag/tests/integration/test_document_public_surfaces.py`.
- [ ] `W05.P10.S109` - Add exhaustive document and combined HTTP reindex routes; `src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_routes.py`.
- [ ] `W05.P10.S110` - Add document counts, generation state, and degraded reasons to HTTP status and readiness; `src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W05.P10.S111` - Add exhaustive targeted document and combined HTTP clean routes; `src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_routes.py`.
- [ ] `W05.P10.S112` - Add document source filters, labels, progress, and detail fields to service job routes; `src/vaultspec_rag/server/_routes_jobs.py`.
- [ ] `W05.P10.S113` - Render document source filters, labels, progress, and details in service job CLI views; `src/vaultspec_rag/cli/_service_jobs.py`.
- [ ] `W05.P10.S114` - Add canonical document and combined search CLI behavior while preserving the existing `docs` alias; `src/vaultspec_rag/cli/_search.py`.
- [ ] `W05.P10.S115` - Add targeted document and combined clean CLI behavior; `src/vaultspec_rag/cli/_index.py`.
- [ ] `W05.P10.S116` - Add document count, policy, generation, and degraded-state CLI status rendering; `src/vaultspec_rag/cli/_status.py`.
- [ ] `W05.P10.S117` - Add document and combined reindex tools with strict source parsing; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W05.P10.S118` - Verify valid and unknown source types and partial outcomes through real HTTP requests; `src/vaultspec_rag/tests/integration/test_document_public_surfaces.py`.
- [ ] `W05.P10.S119` - Verify document index, dry-run, search, clean, status, and service-job rendering through real CLI invocations; `src/vaultspec_rag/tests/integration/test_document_cli.py`.
- [ ] `W05.P10.S120` - Verify document search and reindex behavior through a real MCP session; `src/vaultspec_rag/tests/integration/test_document_mcp.py`.
- [ ] `W05.P10.S125` - Add targeted document and combined clean tools with strict source parsing; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W05.P10.S126` - Add document count, policy, generation, and degraded-state status tools; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W05.P10.S127` - Verify targeted document and combined cleanup through a real MCP session; `src/vaultspec_rag/tests/integration/test_document_mcp.py`.
- [ ] `W05.P10.S128` - Verify document count, policy, generation, and degraded state through a real MCP session; `src/vaultspec_rag/tests/integration/test_document_mcp.py`.

## Wave `W06` - independent acceptance and mandatory review

Consume the completed source-code workload gate and prove independent document behavior. Finish with migration guidance, layout-neutral regression protection, complete project gates, and formal review.

### Phase `W06.P11` - migration guidance and neutrality guards

Explain the explicit configuration migration and protect the generic implementation from acquiring consumer-specific path semantics later.

- [ ] `W06.P11.S75` - Revise preprocessing and indexing guidance through the documentation pipeline for required targets, source profiles, extractor versions, and fail-closed migration; `docs/preprocessing-hooks.md, docs/indexing.md`.
- [ ] `W06.P11.S76` - Revise search and public-interface guidance through the documentation pipeline for document and combined behavior; `docs/search-and-index.md, README.md`.
- [ ] `W06.P11.S77` - Verify admission remains invariant under arbitrary path relocation and ContentKind is never derived from directory names; `src/vaultspec_rag/tests/test_content_policy.py`.

### Phase `W06.P12` - document workload acceptance

Depend on the completed 250,872-chunk representative source-code workload gate and verify the bounded document support profile through production extraction and storage.

- [ ] `W06.P12.S78` - Expose active source and document support profiles and their independent ceilings in service status; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W06.P12.S79` - Generate a separately named document workload with measured source, extracted, chunk, queue, RSS, and CUDA dimensions; `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`.
- [ ] `W06.P12.S80` - Verify over-budget document workloads are refused at job admission before GPU work; `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`.
- [ ] `W06.P12.S81` - Verify bounded document completion, interruption, and resume with representative real formats, extractor processes, CUDA, and Qdrant; `src/vaultspec_rag/tests/benchmarks/bench_document_index_resilience.py`.
- [ ] `W06.P12.S82` - Verify code-only jobs launch no document extractor and code cleanup preserves document collection, metadata, and cache; `src/vaultspec_rag/tests/integration/test_document_lifecycle.py`.
- [ ] `W06.P12.S83` - Verify multi-segment code and document restarts replay only the final unconfirmed unit in each kind; `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`.

### Phase `W06.P13` - complete regression matrix and review

Run focused and complete verification without test shortcuts, then close only after a formal architecture and safety audit reports no unresolved finding.

- [ ] `W06.P13.S84` - Run focused policy, preprocessing, indexer, migration, store, search, watcher, jobs, service, CLI, MCP, restart, and resource suites; `src/vaultspec_rag/tests`.
- [ ] `W06.P13.S85` - Run the complete project test suite without fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures; `pyproject.toml`.
- [ ] `W06.P13.S86` - Run formatting, lint, type, import-boundary, GPU, storage, and policy checks over the completed change; `.pre-commit-config.yaml`.
- [ ] `W06.P13.S87` - Perform the mandatory review for generic routing, fail-closed mutation, document isolation, migration replay, bounded resources, GPU discipline, public exhaustiveness, and test integrity; `.vault/audit/2026-07-22-code-document-index-boundary-audit.md`.

## Parallelization

Waves are ordered. W01 establishes the policy vocabulary, immutable snapshot, and admission
parity before the related resilience plan begins its ledger phase. The related plan owns the
generic ledger schema and restart machinery in its W02. This plan's W02 waits for that restart
gate. This ordering prevents concurrent redesign of `_run_ledger.py`, `_codebase_indexer.py`,
`_code_meta.py`, checkpoint signatures, and generation finalization.

Within W01, P01 precedes P02. Within W02, P03 precedes P04 because ingestion can't target a
collection before its model and lifecycle exist. Within W03, command and entry-point envelope
steps may proceed in parallel. When work shares `_chunk_worker.py`,
`_preprocess_runner.py`, or `_streaming.py`, sequence cache, convergence, and execution-budget
changes by dependency.

W04 follows the related resilience W02 gate and this plan's W02-W03. P07 establishes
publication identity before P08 mutates legacy ownership. In W05, implement the closed source
parser and service-domain query behavior before HTTP, transport, CLI, or MCP adapters. W06 is
strictly last.

When their production files don't overlap, policy and schema tests that use only CPU resources
may run in parallel. Serialize real CUDA, local Qdrant, resident-service Qdrant, and benchmark
runs because they share machine-level GPU and backend resources. Documentation steps use the
documentation pipeline. The final review uses the code-review workflow.

## Verification

- Plan validation reports canonical L3 Wave, Phase, and Step paths, contiguous rows, complete
  authorizing frontmatter, and no placeholder, link, or row-contract error.
- Admission never derives `ContentKind` from a built-in directory, package, product, project,
  or client name. With equivalent caller-authored routes, arbitrary path-placement
  permutations preserve ownership.
- Ignore rules win for every content kind. One path has at most one owner in a policy
  snapshot, conflicting ownership fails closed, and parser capability never establishes
  membership.
- Full discovery, scoped discovery, watcher classification, API scan, CLI dry-run, and
  service preflight return identical content kind and stable disposition reason from one
  immutable snapshot.
- Missing targets, unknown targets, conflicting routes, and malformed policy return
  structured migration or configuration errors before collection, metadata, ledger, cache,
  writer, or GPU mutation.
- Disabling preprocessing preserves routing knowledge, marks affected work disabled or stale,
  and performs no deletion or reclassification.
- Code collections contain source-only chunks. Document collections preserve document-specific
  identity, metadata, locator, extractor, count, lifecycle, and result-label contracts.
- Options, extractor version, execution mode, schema, source path, and source hash participate
  in cache identity. Path-dependent output cannot cross source paths, and collection cleanup
  does not invalidate unrelated extraction cache.
- Only indexed and stable policy-rejected files converge. Extraction, decoding, and chunking
  failures remain visible with retained reasons and retry obligations.
- Legacy mixed state converges with valid, missing, stale, and partial generation-metadata
  sidecars. Target flips publish and checkpoint the destination before origin deletion and
  replay idempotently. Existing source point identifiers remain stable.
- Keep code and document generations, checkpoints, retry state, circuits, counts, and profiles
  independent. Share one writer authority, one GPU consumer, bounded queues, memory policy,
  and safe points.
- Unknown public source types fail structurally. `document` is canonical, `docs` retains its
  existing vault meaning, and `all` reports explicit per-domain partial outcomes.
- Independent and combined searches define candidate allocation, filtering, reranking, final
  top-k, and result labels explicitly and score real stored content.
- Real source-input, extracted-byte, chunk, queue, RSS, and CUDA gates terminate with typed
  outcomes and preserve the last confirmed checkpoint. A code-only run starts no document
  extractor.
- Every new test imports production behavior and uses real files, subprocess extraction,
  stores, service routes, and adapters. Tests don't use fake, mock, stub, patch, monkeypatch,
  skip, or expected-failure shortcuts.
- Focused suites, the complete suite, pre-commit checks, independent workload benchmarks, and
  restart tests pass. The mandatory audit reports no unresolved architecture, migration,
  resource, GPU, storage, operability, or test-integrity findings.
