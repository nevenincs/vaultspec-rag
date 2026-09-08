---
tags:
  - '#research'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ffed0e5775e10dd651233d751946472bdd1bc46d577738e7d0dc3d68c8c79471'
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
verification reserved for rebuild, recovery, and audit. The ADR must settle proof
ownership, crash ordering, reader behavior during in-place publication, and a hard
current-format cutover that refuses old persisted evidence instead of translating it.

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
replayed or reconciled after restart. Pre-proof, foreign, wrong-parent, or policy-drift
evidence cannot be translated into proof and requires explicit rebuild authority.

### Fresh schema creation and old-format migration are separate operations

The current ledger initialization accepts schema version 6 and then installs publication
tables additively at `src/vaultspec_rag/indexer/_run_ledger_runtime.py:401` and
`src/vaultspec_rag/indexer/_run_ledger_runtime.py:481`. Because the pre-proof and
proof-bearing layouts share `SCHEMA_VERSION = 6` at
`src/vaultspec_rag/indexer/_run_ledger_models.py:474`, that path cannot fail before it
mutates an old database. The same compatibility surface includes the
`INEXACT_LEGACY_EVIDENCE` status at
`src/vaultspec_rag/indexer/_publication_proof.py:86` and the `legacy:unknown` signature
default and decoder fallback at `src/vaultspec_rag/indexer/_run_ledger_models.py:782` and
`src/vaultspec_rag/indexer/_run_ledger_runtime.py:1080`. A current-format-only design
therefore needs a distinct schema version, exact creation for an empty database, typed
rebuild refusal before mutating any older database, and removal of those legacy values.

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

### Reader safety requires a proof fence, not ordering alone

Storage-first ordering prevents proof from leading storage but does not stop a live reader
from observing a mutation whose proof is still old. The safe bounded protocol is a
seqlock-style token: read the current revision while no receipt is open, query storage,
then validate the same revision and receipt absence. A changed token is transiently
unverifiable or retried; it is never accepted as complete.

### Streaming publication requires intent before each mutation unit

Exact point membership is learned during streaming, after a whole-delta prepare point would
already be too late. Evidence favors reserving one parent-to-target revision, durably
preparing each bounded mutation unit before its store call, confirming it after storage
acknowledgement, sealing the complete path delta before destructive reconciliation, and
committing only when every required unit is confirmed.

### Sparse current state must not become an unbounded ancestry chain

Removing parent snapshot copies without a replacement makes inherited reads disappear and
deleted child paths reveal parent rows. A current normalized proof projection should remain
bounded: committed heads plus sparse generation-local overrides and deletion tombstones are
folded atomically at proof commit. Historical generations remain provenance rather than the
normal lookup structure. Destructive routing currently obtains file states and retained
point ids through separate calls at `src/vaultspec_rag/indexer/_route_migration.py:585` and
`src/vaultspec_rag/indexer/_route_migration.py:586`; an effective read must return both from
one receipt-bound ledger snapshot or a proof revision can change between authorization and
deletion.

### Proportionality includes routing and stat evidence

The scoped path still rewrites the complete stat-evidence JSON map and may perform full
route reconciliation or materialize all retained ids. These operations violate the same
steady-state cost bound as sidecar serialization. They require normalized changed-key
updates or explicitly authorized full-sweep paths.

### A no-fallback cutover has one safe direction

Breadth, donor, survey, reclamation, archive, and cleanup consumers currently read
sidecars, while code, document, and vault publication still produces them. Stopping those
writes first can leave old readers certifying stale evidence. Moving readers first to the
canonical proof fails closed until an explicitly authorized rebuild creates current proof,
which is safe even though it is temporarily unavailable. A selector, fallback, sidecar
translation, or dual write would avoid that availability edge only by creating a second
authority. The evidence therefore favors this order: make rebuild authority operational,
cut every reader directly to canonical proof with typed rebuild-required refusal, switch
all producers to canonical proof, then delete the now-unused sidecar and generation-copy
code. Vault must enter the same source-neutral coordinator despite retaining its own
classification and payload adapter. Receipt history, evidence owners, cleanup, archive,
and compaction still need bounded retention rules so no exposed proof references reclaimed
state. The reader-first and producer-second commits are safe development states because
they fail closed, but the evidence does not support releasing between them; all three
producer cutovers and legacy-code deletion form the same release boundary as reader cutover.

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
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py:236`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py:401`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py:481`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py:1080`
- `src/vaultspec_rag/indexer/_run_ledger_models.py:474`
- `src/vaultspec_rag/indexer/_run_ledger_models.py:782`
- `src/vaultspec_rag/indexer/_publication_proof.py:86`
- `src/vaultspec_rag/indexer/_run_ledger_files.py:456`
- `src/vaultspec_rag/indexer/_run_ledger_commits.py:115`
- `src/vaultspec_rag/indexer/_run_ledger_commits.py:519`
- `src/vaultspec_rag/indexer/_run_ledger_finalization.py:88`
- `src/vaultspec_rag/indexer/_run_ledger_finalization.py:260`
- `src/vaultspec_rag/indexer/_streaming.py:698`
- `src/vaultspec_rag/indexer/_stat_gate.py:283`
- `src/vaultspec_rag/indexer/_consumer_pipeline.py:270`
- `src/vaultspec_rag/indexer/_route_migration.py:615`
- `src/vaultspec_rag/indexer/_route_migration.py:585`
- `src/vaultspec_rag/indexer/_route_migration.py:586`
- `src/vaultspec_rag/generation_survey.py:105`
- `src/vaultspec_rag/indexer/_vault_indexer.py:79`
- `src/vaultspec_rag/job_manager/models.py:27`
- `src/vaultspec_rag/job_models.py:596`
- `src/vaultspec_rag/job_manager/_persistence.py:430`
