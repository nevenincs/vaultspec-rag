---
tags:
  - '#reference'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8d91b72a0e61ee24d2cfc1e4ebd89939b03385cbfc0a95b6f88f8aa4f02e0c84'
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
