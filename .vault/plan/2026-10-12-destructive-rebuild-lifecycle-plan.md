---
tags:
  - '#plan'
  - '#destructive-rebuild-lifecycle'
date: '2026-10-12'
tier: L1
related:
  - '[[2026-10-12-destructive-rebuild-lifecycle-adr]]'
  - '[[2026-09-07-explicit-reindex-authority-adr]]'
  - '[[2026-09-08-search-readiness-contract-adr]]'
  - '[[2026-09-08-incremental-publication-cost-adr]]'
  - '[[2026-09-01-generation-accounting-adr]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-07-21-code-document-index-boundary-adr]]'
  - '[[2026-07-25-index-lifecycle-consolidation-adr]]'
  - '[[2026-05-30-cli-index-default-adr]]'
  - '[[2026-07-25-storage-conformance-adr]]'
modified: '2026-10-12'
body_schema: body-v2
body_hash: 'sha256:e868f0474731783c3e1664b989b2f1527637bf9cd8f0c1eaa3d6efffa5e8d86f'
---

# `destructive-rebuild-lifecycle` plan

## Description

Architecture revision authorized 2026-10-12 by the user's direction to discard the old index on rebuild, unify code/vault/document behavior, create a feature branch, and preserve concurrent indexing and search. Branch: `feature/destructive-rebuild-lifecycle`. This plan sequences runtime implementation of that architecture; the current request authorizes the architecture records and branch, not a live reset or service rollout. Runtime Steps remain open.

The new rebuild ADR governs the reset and progressive-serving contract for all Steps. Explicit-reindex authority governs operation admission; generation accounting and incremental-publication cost govern storage-before-proof and source-scoped durable evidence; search readiness governs immediate, bounded, and combined outcomes; large-index resilience and service-job-control govern recovery and cooperative control. Service concurrency governs capacity/locks and the code-document boundary governs separate content producers and state partitions. Lifecycle consolidation keeps one event owner alongside one rebuild coordinator.

Reader, producer, and reset changes are one release boundary. Intermediate commits must not be deployed independently. Keep ordinary incremental work proportional, existing GPU ownership and resource ceilings intact, and automatic maintenance separate from explicit reset. Source inspection and evidence are inherited from the ADR's Reference.

## Steps

- [ ] `S01` - Implement one source-neutral durable reset owner with selected-source proof invalidation, verified hard deletion, canonical collection recreation, epoch fencing, and reset crash recovery; `src/vaultspec_rag/indexer/_rebuild_lifecycle.py (create), tests/test_rebuild_lifecycle.py (create), store_collections.py, _store_models.py, _publication_state.py, indexer/_run_ledger_*`.
- [ ] `S02` - Route code, vault, and document full-index entry points through the shared reset lifecycle and write fresh batches into one live target; remove preservation branches and certify that same target at completion; `src/vaultspec_rag/indexer/{_codebase_indexer.py,_vault_indexer.py,_document_indexer.py,_generation_lifecycle.py,_checkpoint_common.py,_index_lifecycle.py}, their streaming/checkpoint collaborators, and rebuild/publication tests`.
- [ ] `S03` - Serve compatible partial current-epoch results during ingestion and fence reads crossing reset; keep completeness certification distinct from useful retrieval across immediate, bounded, and combined search; `src/vaultspec_rag/{_search_state.py,_index_integrity.py,_publication_state.py,_public_search.py,api.py,service.py}, server/{_search_readiness.py,_search_availability.py,_search_route_availability.py,_routes_search.py}, and search readiness/service tests`.
- [ ] `S04` - Distinguish new rebuilds from same-generation resume and linked retry, acknowledge controls at durable units, and prevent old attempts or watcher updates from corrupting a replacement; `src/vaultspec_rag/{job_dispatch.py,job_control.py,job_manager/}, indexer/{_run_policy.py,_run_checkpoint.py,_checkpoint_common.py}, watcher settlement, tests/test_job_rebuild_resume_dispatch.py and tests/integration/test_index_job_control_publication.py`.
- [ ] `S05` - Complete explicit selected-source cutover of historical generation layouts; remove shadow publication and retention machinery while preserving unrelated maintenance and source partitions; `src/vaultspec_rag/{_store_models.py,store_collections.py,store_runtime.py,generation_survey.py,generation_stamps.py,storage_reclamation.py}, survey/status/donor consumers, and generation cleanup/isolation tests`.
- [ ] `S06` - Align CLI/API job admission, partial search/status rendering, and rebuild documentation; prove the integrated three-domain reset/search/recovery contract and complete final review; `src/vaultspec_rag/{cli/_index.py,_operator_commands.py,server/_routes_reindex.py,server/_routes_jobs.py,mcp/_tools.py}, README.md, relevant docs/ command guides, and real service/storage integration and concurrency tests`.

## Parallelization

Execute sequentially. The reset state, three producers, publication evidence, and readiness consumers share contracts and files. No concurrent worker assignments are declared.

## Verification

Use production entry points and real temporary storage. The acceptance matrix covers code, vault, and document independently, plus all-domain orchestration, local and server backends, and HTTP/CLI/MCP search projections. No test writes to the operator's storage or resets a live root.

For every domain, seed recognizable old-only content, begin an explicit rebuild, and prove old points are absent before the first replacement write. Verify the canonical collection is empty at reset completion. Search for recognizable fresh content after a bounded applied batch while further ingestion is still pending: return useful partial results before final publication, with no old content and non-authoritative absence. Repeat with pauses, cancellation, failure, restart, and a new explicit rebuild. A complete empty corpus returns authoritative empty success only after finalization.

Exercise crashes before/after durable reset intent, backend deletion, empty creation, reset commit, applied writes, unit checkpoint, and final proof commit. Same-generation recovery must not drop confirmed replacement work; a new rebuild must not silently resume an older generation. Drain or fence stale writers and reject cross-epoch reads. A local same-name recreate must not resurrect deleted files. Inject failed deletion and surviving local directories and prove ingestion never begins.

Prove sibling source data, ledger partitions, and unrelated roots remain intact. Test historical code-generation cleanup only under explicit selected-source reset, with unknown/foreign names refused. Prove queued/refused jobs do not delete, incremental/MCP refresh cannot reach reset, and repeated request IDs reset at most once. Validate model/schema mismatches and source changes during pause without mixing epochs.

Measure simultaneous same-source and cross-source searches while indexing through real service capacity and GPU ownership. Both workloads must make progress; search must not wait for corpus completion. Record latency distributions and indexing throughput against the current baseline, plus phase/wait timings and peak storage. Reject any whole-job search serialization, added GPU owner, unbounded queue, or retained old collection. This plan asserts no unmeasured speedup or zero transient latency.

Run project lint, formatting, strict type checks, targeted real-storage/service tests, and mutation proofs for new negative guards. Reuse applicable verification evidence across the final integrated review. Completion requires every Step closed and that review passing; writing this plan does not satisfy runtime verification.
