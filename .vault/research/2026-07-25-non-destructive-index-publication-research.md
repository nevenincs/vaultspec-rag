---
tags:
  - '#research'
  - '#non-destructive-index-publication'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-completeness-guard-adr]]"
  - "[[2026-07-25-index-completeness-guard-audit]]"
  - "[[2026-07-23-chunk-id-uniqueness-adr]]"
---

# `non-destructive-index-publication` research: `how a clean rebuild empties a served index and why the cheap fix is wrong`

A production operator reports that a code index periodically drops to zero points
and that runs described as incremental hash tens of thousands of files, while
search over the same root returns nothing and then partially recovers. The
question is what empties the collection, whether serving and indexing contend,
and what the minimum correct remedy is. `2026-07-25-index-completeness-guard-adr`
already records the truncation window as a known deferred risk; this document
establishes the trigger, rules out the cheap remedy, and gathers the storage
constraints any remedy has to satisfy.

## Findings

### F1 - An unattended incremental escalates itself into a destructive rebuild

The resident watcher requests incremental reindexing on file change
(`src/vaultspec_rag/watcher.py:810`), under a per-source cooldown. The
incremental entry point applies three escalation gates in order
(`src/vaultspec_rag/indexer/_codebase_indexer.py:2754`). Two of them call
`_full_index_locked(clean=True)`: a stale embed-input format
(`:2781`) and content-shaping config drift (`:2795`). A `clean=True` run drops
the collection and repopulates it incrementally, so the zero-point window spans
the whole repopulation rather than an atomic swap.

Nothing in that path carries an operator request. The watcher asked for a
reconcile; the indexer decided on its own to destroy the served data. This is
the trigger the operator observes, and it explains the correlation with indexing
rather than with query load.

### F2 - Serving and indexing do not contend for the collection

The reported degradation is not lock contention. Locking is per-collection with
no store-wide mutex, and a remote server owns its own concurrency. Search returns
zero because the points are absent, not because a reader is blocked. Any remedy
aimed at lock scope or thread scheduling would leave the symptom unchanged.

### F3 - The full-rehash symptom is the completeness guard re-firing

`_published_evidence_lost` (`src/vaultspec_rag/indexer/_codebase_indexer.py:1662`)
escalates to failure-safe full reconciliation whenever the live point count falls
short of the figure the sidecar published. An interrupted `clean=True` run leaves
a fragment beneath a sidecar still describing the whole corpus, so every later
incremental sees a shortfall and reconciles the entire tree. Where the watcher
retriggers before a reconcile completes, the shortfall never clears and the
condition is self-sustaining. The guard converted a silent latch into a loud one;
it did not create the window it detects.

### F4 - Escalating to `clean=False` instead is incorrect

The obvious cheap fix - have the two gates escalate to failure-safe
reconciliation rather than a destructive rebuild - does not achieve what the
gates exist for. Chunk identity embeds a content hash
(`2026-07-23-chunk-id-uniqueness-adr`), so re-encoding a file under a new regime
writes points under new identifiers rather than overwriting the old ones. The
superseded points survive, and the mixed-regime retrieval degradation that
justified `clean=True` persists. A remedy must still remove the old points; it
may not do so by emptying what is currently being served.

### F5 - There is no alias primitive, and local mode constrains the swap

The store exposes collection creation and deletion
(`src/vaultspec_rag/store.py:619`, `:717`, `:748`) and no alias operation. Qdrant
aliases, the usual atomic-swap mechanism, are a server-mode feature, so a single
uniform swap is not available across the two backends this project supports.

Local mode carries a documented additional hazard: `delete_collection` pops the
in-memory handle while the on-disk directory survives, and a same-name
`create_collection` re-reads it (`src/vaultspec_rag/store.py:717-748`). A
build-then-swap scheme that reuses the served name in local mode has to account
for that resurrection behaviour rather than assume delete-then-create is clean.

### F6 - Peak storage is a live constraint

A duplicate collection during the swap roughly doubles peak footprint for the
root being rebuilt. The backend has previously been observed holding tens of
collections and hundreds of thousands of points, and preallocation rather than
data dominates the footprint, so headroom cannot be assumed. Any scheme holding
two full copies needs a stated position on what happens when the swap cannot be
afforded.

### F7 - The search-availability guard does not cover the aftermath

The 503 contract for non-authoritative empty responses
(`2026-07-21-search-index-availability-adr`) fires only while a matching
nonterminal job is observed on both sides of retrieval. A rebuild that fails and
terminates leaves a truncated collection with no matching job, so an empty search
over the fragment returns HTTP 200 and reads as authoritative. Detection of the
shortfall is carried on the response, but the window between a failed rebuild and
the next reconcile is not covered by the 503 rule.

## Sources

- `src/vaultspec_rag/watcher.py:810` - watcher requests incremental reindexing
- `src/vaultspec_rag/indexer/_codebase_indexer.py:2754` - incremental entry point
  and its escalation gates
- `src/vaultspec_rag/indexer/_codebase_indexer.py:2781` - embed-format gate,
  `clean=True`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:2795` - config-drift gate,
  `clean=True`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1662` - published-evidence
  shortfall predicate
- `src/vaultspec_rag/store.py:619` - collection creation
- `src/vaultspec_rag/store.py:717-748` - hard delete and the local-mode
  directory-survival hazard
- `2026-07-23-chunk-id-uniqueness-adr` - chunk identity embeds a content hash
- `2026-07-25-index-completeness-guard-adr` - records the truncation window as
  deferred follow-up
- `2026-07-25-index-completeness-guard-audit` - recommends build-into-shadow and
  atomic swap
- `2026-07-21-search-index-availability-adr` - the 503 contract and its matching
  requirement
