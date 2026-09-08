---
tags:
  - '#reference'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:3565c4d5c90d1566efd149ce2564e416d36a1d302b569860013494e71e841c18'
related:
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-25-non-destructive-index-publication-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `incremental-publication-cost` reference: `publication proof seams`

## Summary

The canonical code commit seam is `CodeIncrementalCommit.commit_replacement()` at
`src/vaultspec_rag/indexer/_incremental_commit.py:266`. Scoped indexing clones the
complete prior hash map at `src/vaultspec_rag/indexer/_codebase_indexer.py:1252`, then
passes it through that seam. Checkpointed publication delegates to the single
`CodeGenerationLifecycle.publish()` authority at
`src/vaultspec_rag/indexer/_generation_lifecycle.py:344`.

That authority records an exact point count and then calls `count_code_files()` at
`src/vaultspec_rag/indexer/_generation_lifecycle.py:375`. The latter scrolls the whole
collection to materialize distinct paths at `src/vaultspec_rag/store_catalog.py:647`.
Code metadata publication also streams every publishable ledger state and atomically
rewrites the complete JSON sidecar at `src/vaultspec_rag/indexer/_code_meta.py:188`.

The same cost shape exists in the other domains. Document metadata is a complete,
path-sorted manifest including every retained point id at
`src/vaultspec_rag/indexer/_document_meta.py:84`, and publication reconstructs and
rewrites it at `src/vaultspec_rag/indexer/_document_meta.py:264`. Scoped vault indexing
copies the complete prior hash map at `src/vaultspec_rag/indexer/_vault_incremental.py:730`;
its publication scans all stored ids for distinct documents and rewrites the full map at
`src/vaultspec_rag/indexer/_vault_indexer.py:800`.

The canonical extension point is the existing durable finalization owner, not another
sidecar cache. `RunCheckpointBase.publish_metadata_transition()` owns the transition to
metadata-published at `src/vaultspec_rag/indexer/_checkpoint_common.py:194`, confirmed
per-path deletions already enter the ledger at
`src/vaultspec_rag/indexer/_checkpoint_common.py:233`, and
`RunCheckpointBase.publish_generation()` requires metadata before generation publication
at `src/vaultspec_rag/indexer/_checkpoint_common.py:306`. The phase ordering is durable
at `src/vaultspec_rag/indexer/_run_ledger_models.py:466`.

Existing proof semantics must remain explicit by source. Code carries published points,
distinct files, generation, and backend identity through
`src/vaultspec_rag/_index_breadth.py:370`; vault carries the analogous document evidence
at `src/vaultspec_rag/_index_breadth.py:408`; document breadth derives from its retained
point identities at `src/vaultspec_rag/indexer/_document_meta.py:119`. A shared proof
owner can normalize these invariants while preserving source-specific identity and policy
fields.

The strongest test seams are the publication-owner guard at
`src/vaultspec_rag/tests/test_process_probe_ownership_guards.py:26`, finalization restart
coverage at `src/vaultspec_rag/tests/test_run_checkpoint.py:398`, scoped code integration
at `src/vaultspec_rag/tests/integration/test_codebase_integration.py:318`, document store
integration at `src/vaultspec_rag/tests/integration/test_document_store.py:141`, and vault
breadth integration at
`src/vaultspec_rag/tests/integration/test_vault_chunking_integration.py:220`.

The current generation ledger cannot replace its eager parent-manifest copy in one
runtime-only change. Child reads and mutations assume physical ownership of a complete
`file_states` snapshot: `_carry_published_manifest()` copies it at
`src/vaultspec_rag/indexer/_run_ledger_runtime.py:236`, while effective reads live at
`src/vaultspec_rag/indexer/_run_ledger_files.py:456` and retained-point reads at
`src/vaultspec_rag/indexer/_run_ledger_commits.py:519`. Finalization and compaction make
the same assumption at `src/vaultspec_rag/indexer/_run_ledger_finalization.py:88` and
`src/vaultspec_rag/indexer/_run_ledger_finalization.py:260`. Sparse inheritance therefore
requires deletion tombstones and ancestry-aware reads before the copy can be removed.

The backend transaction gap also reaches readers. Commit units are recorded after storage
at `src/vaultspec_rag/indexer/_run_ledger_commits.py:115`; streaming code discovers exact
point membership during writes at `src/vaultspec_rag/indexer/_streaming.py:698`. A receipt
that requires the complete delta before streaming cannot cover the first mutation. Search
must additionally fence a backend read with a stable proof revision and absence of an open
receipt, because storage-first ordering alone permits a reader to observe mixed storage and
proof generations.

Additional corpus-wide work lies outside the original publication seams. Scoped hashing
rewrites the complete stat-evidence map at `src/vaultspec_rag/indexer/_stat_gate.py:283`;
code materializes all retained identities at
`src/vaultspec_rag/indexer/_consumer_pipeline.py:270`; and route reconciliation scrolls
same-kind and cross-kind collections at
`src/vaultspec_rag/indexer/_route_migration.py:615`. Generation protection still reads
sidecars at `src/vaultspec_rag/generation_survey.py:105`, so proof readers must cut over
before producers stop writing those sidecars.

Vault does not currently share the code/document generation lifecycle: its entry point at
`src/vaultspec_rag/indexer/_vault_indexer.py:79` has no run-ledger checkpoint owner, and
its streaming writes lack pre-mutation receipt hooks. Durable service telemetry also crosses
separate contracts in `src/vaultspec_rag/job_manager/models.py:27`,
`src/vaultspec_rag/job_models.py:596`, and
`src/vaultspec_rag/job_manager/_persistence.py:430` rather than ending at dispatch.
