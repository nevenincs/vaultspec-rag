---
tags:
  - '#research'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:5654631aad5d872c6308e655778e61365926a9a90d130ebb69a7053c58d44193'
related:
  - "[[2026-09-08-incremental-publication-cost-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-research]]"
  - "[[2026-07-25-index-completeness-guard-research]]"
  - "[[2026-07-25-non-destructive-index-publication-research]]"
---

# `incremental-publication-cost` research: `exact delta publication`

## Findings

Scoped publication is not proportional today: it scans collection-wide identities and
reconstructs complete metadata manifests while the writer lease is held. The evidence
favors an exact normalized proof updated from storage-confirmed path deltas, with full
verification reserved for rebuild, migration, recovery, and audit. The ADR must settle
proof ownership, crash ordering, reader behavior during in-place publication, and legacy
migration.

### Two independent operations scale with the corpus

Code publication scrolls all points for distinct paths at
`src/vaultspec_rag/store_catalog.py:647` and reconstructs the complete sidecar through
`src/vaultspec_rag/indexer/_code_meta.py:188`. Scoped code first copies the prior map at
`src/vaultspec_rag/indexer/_codebase_indexer.py:1252`. Document and vault publication
repeat the pattern at `src/vaultspec_rag/indexer/_document_meta.py:264` and
`src/vaultspec_rag/indexer/_vault_incremental.py:730`. Removing only the scroll therefore
leaves O(total indexed identities) serialization.

### Exact deltas already meet a durable commit boundary

The ledger records storage-confirmed path identities and deletions before finalization at
`src/vaultspec_rag/indexer/_checkpoint_common.py:194` and
`src/vaultspec_rag/indexer/_checkpoint_common.py:233`. Exact aggregate points change by
`new_points - old_points`; indexed path breadth changes only when old and new indexed
states differ. Rename is delete-plus-add, empty or ignored content removes prior breadth,
and no-op changes nothing. A verified parent proof can therefore advance without a scan.

### One normalized proof fits existing ownership

A source-scoped proof beside the ledger can bind backend, collection, generation, schema,
policy, and source identity while retaining normalized per-path hashes and point evidence
plus exact aggregates. The shared metadata transition and generation-last ordering at
`src/vaultspec_rag/indexer/_checkpoint_common.py:194` and
`src/vaultspec_rag/indexer/_checkpoint_common.py:306` are the canonical owner. Another
cache or sidecar would duplicate invalidation, rollback, and restart semantics.

### Crash recovery needs an idempotent receipt

Prepare the exact delta durably against a parent proof revision, apply deterministic
storage mutations, cross a storage-confirmed barrier, then commit proof rows, aggregates,
revision, and receipt status in one local transaction. Clean rebuilds retain pointer-last
publication at `src/vaultspec_rag/indexer/_generation_lifecycle.py:352`. Prepared work is
replayed or reconciled after restart; legacy, foreign, wrong-parent, or policy-drift
evidence remains unverifiable and requires explicit rebuild authority.

### Full verification remains exceptional and authoritative

An explicit integrity operation still scans backend ids and source identities to detect
missing or extra points, foreign evidence, schema or policy drift, and partial generations.
Telemetry must separate changed paths, proof rows, point mutations, data commit, proof
update, and writer-lease time from full-verification breadth and duration.

### Alternatives fail a governing constraint

An append-only delta chain shifts unbounded cost to reads or compaction. A Merkle root
cannot establish backend contents without leaf evidence. Cached counts plus full JSON
retain O(total) serialization and fragile invalidation. Shadow-copying each incremental is
also O(total). Normalized bounded row updates are the only investigated option combining
exactness, durable replay, and changed-scope steady-state cost.

### Open questions

The ADR and plan must resolve reader exclusion during in-place mutation, backend write
consistency, managed-Qdrant out-of-band equal-cardinality drift, vault lifecycle
integration, and proof-history retention. These affect sequencing, not the need to remove
full scans and rewrites from the normal path.

## Sources

- `src/vaultspec_rag/store_catalog.py:647`
- `src/vaultspec_rag/indexer/_code_meta.py:188`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1252`
- `src/vaultspec_rag/indexer/_document_meta.py:264`
- `src/vaultspec_rag/indexer/_vault_incremental.py:730`
- `src/vaultspec_rag/indexer/_checkpoint_common.py:194`
- `src/vaultspec_rag/indexer/_checkpoint_common.py:233`
- `src/vaultspec_rag/indexer/_checkpoint_common.py:306`
- `src/vaultspec_rag/indexer/_generation_lifecycle.py:352`
