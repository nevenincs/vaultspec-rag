---
tags:
  - '#reference'
  - '#destructive-rebuild-lifecycle'
date: '2026-10-12'
modified: '2026-10-12'
body_schema: 'body-v2'
body_hash: 'sha256:7b5af1b7c1106de11b34ec9f22937f735abe43baeeaa72a565739515272f2271'
related: []
---

# `destructive-rebuild-lifecycle` reference: `reset and concurrent search seams`

## Summary

Inspected main at commit `380e875fe92d223431dfe0d30ec60c5a7f613c6b` on 2026-10-12. This is source inspection, not a runtime acceptance test. The earlier semantic code query returned `index_unverifiable`; targeted source inspection supplied the code evidence. Vault semantic search located the preservation decision and its dependent records. The service installation directory is not evidence of an architecture defect: this repository implements the service installed into the uv tool environment.

### Current rebuild behavior differs by domain

Code rebuild authority opens a clean checkpoint and derives a separate collection in `src/vaultspec_rag/indexer/_generation_lifecycle.py:289`. Preparation creates that collection without dropping the served one in `src/vaultspec_rag/indexer/_codebase_indexer.py:606`. Publication reconciles the build collection, records proof, and moves the served pointer in `src/vaultspec_rag/indexer/_generation_lifecycle.py:321`. The pointer write is atomic in `src/vaultspec_rag/_store_models.py:671`. An ordinary incremental run instead writes the served collection.

Vault full indexing snapshots live identities, streams replacements into the live collection, and then removes stale entries in `src/vaultspec_rag/indexer/_vault_indexer.py:318`. Its collection preparation drops only on incompatible geometry under clean authority in `src/vaultspec_rag/indexer/_vault_indexer.py:668`. Document full indexing also replaces in place and retains a geometry-triggered recreate branch in `src/vaultspec_rag/indexer/_document_indexer.py:1225`. Updating live points is not an immutable old snapshot: old and new payloads can coexist during the run.

The preservation contract is explicit in `2026-07-25-non-destructive-index-publication-adr`. Code implemented the shadow strategy, while vault and document implemented in-place preservation. The shared wrapper in `src/vaultspec_rag/indexer/_index_lifecycle.py:94` unifies events and activity stamping only; it does not own reset, serving identity, or publication. `2026-07-25-index-lifecycle-consolidation-adr` expressly limited its scope to those events and stamps. Domain-specific parsing does not require these different rebuild semantics.

### A verified hard-delete primitive already exists

`src/vaultspec_rag/store_collections.py:181` closes local handles before deletion and checks that the local collection directory disappeared. This prevents the same-name recreation hazard described by the old preservation decision. `_drop_collection` takes lifecycle-before-collection locks and clears the ensure latch in `src/vaultspec_rag/store_collections.py:209`. The domain drop methods are at lines 222, 243, and 254. The current code drop resolves its served pointer; a cutover must cover both derived and previously generation-named code collections owned by the selected root.

The primitive does not by itself fence old writer attempts, invalidate cached store bindings across readers, or persist a reset phase. Those belong to the shared rebuild lifecycle. No storage deletion was performed during this investigation.

### Publication evidence is stronger than useful partial retrieval

`src/vaultspec_rag/_publication_state.py:70` acquires the canonical ledger proof and read token. `src/vaultspec_rag/_publication_state.py:118` clears publication authority for one root, backend, and source before storage deletion. The ledger is shared across source kinds; deleting the database to reset one source would violate source isolation.

`src/vaultspec_rag/server/_search_route_availability.py:301` classifies results and suppresses a non-authoritative empty success. The canonical readiness model separates usability, freshness, and absence authority in `src/vaultspec_rag/_search_state.py:72`. The route currently derives served identity from published identity at `src/vaultspec_rag/server/_search_route_availability.py:159`; partial serving needs an explicit current reset epoch without pretending publication already happened.

`2026-09-08-incremental-publication-cost-adr` uses open receipts to prevent complete-proof certification during mutations. That protects completeness, but cannot be used as a whole-rebuild search gate if fresh batches must remain searchable. A partial read needs compatible current-epoch storage and non-authoritative absence semantics; a complete read still needs the existing certified proof. Storage-confirmed progress and final completeness are separate facts in the same durable authority.

### Retention is an architectural consequence of the shadow strategy

`src/vaultspec_rag/generation_survey.py` discovers unreferenced code generations. The maintenance adapter passes the data grace window into reclamation in `src/vaultspec_rag/storage_reclamation.py:764`; its configured default is 168 hours in `src/vaultspec_rag/config/_settings.py:155`. `_drop_generation_collections` removes eligible old collections at `src/vaultspec_rag/storage_reclamation.py:989`. Reset-first rebuilding can retire that feature for newly rebuilt indexes instead of retaining an old generation until a later maintenance cycle.

### Existing authority and resource boundaries to retain

`2026-09-07-explicit-reindex-authority-adr` forbids automatic incremental escalation. `2026-06-12-service-concurrency-adr` provides dedicated search/index capacity and backend-aware point locking. `2026-07-21-large-index-resilience-adr` supplies the shared source-partitioned ledger, storage-before-checkpoint ordering, bounded units, and restart recovery. `2026-07-21-service-job-control-adr` supplies acknowledged cooperative controls. Their whole-rebuild protected interval and preservation clauses need scoped revision; their resource and authority boundaries remain useful.

The existing test surfaces include `src/vaultspec_rag/tests/test_code_rebuild_stale_evidence.py`, `src/vaultspec_rag/tests/test_job_rebuild_resume_dispatch.py`, `src/vaultspec_rag/tests/test_publication_read_paths.py`, `src/vaultspec_rag/tests/test_publication_recovery.py`, `src/vaultspec_rag/tests/test_search_readiness.py`, and `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`. New acceptance must prove deletion before the first replacement batch and useful searches before the last batch for each domain, rather than preserving the previous generation as its expected result.
