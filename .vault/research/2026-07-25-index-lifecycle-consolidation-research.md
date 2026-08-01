---
tags:
  - '#research'
  - '#index-lifecycle-consolidation'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:0351a3a792800acfde738b23a132e0aa64cb18425a6b1366ca70718f9c265fdb'
related: []
---

# `index-lifecycle-consolidation` research: `activity clock and index event reachability across the three indexers`

The question was how far the document indexer's silence actually reaches. It
takes the writer lock and runs a full pass while stamping no activity clock and
emitting no index event, where the code and vault indexers do both. Two things
had to be separated before the gap could be priced: whether a document-only run
can reach a destructive maintenance decision while presenting a stale clock,
and what an operator concretely loses from the missing events.

The evidence separates them cleanly. The destructive exposure is real but
narrow - it is gated behind a temp-rooted namespace in server mode, and it is
the whole root's clock at stake rather than the document collection's. The
observability loss is unconditional and applies to every root. Neither is
argued from the copy count; the copy count is why the gap existed, not why it
matters.

## Findings

### One clock per root, shared by all three collections

The stamp is keyed by root, not by collection. `record_root` derives its key
from `root_collection_prefix(root)` (`src/vaultspec_rag/storage_manifest.py:349`)
and the manifest holds one `last_indexed` field per entry
(`src/vaultspec_rag/storage_manifest.py:123`). The vault, code, and document
collections of one root therefore share a single activity clock.

This cuts both ways. It is why the gap went unnoticed - any code or vault run
on the same root refreshes the clock the document run failed to refresh, so
mixed workloads mask the defect entirely. It is also what makes the remaining
exposure specific: only a root whose indexing is document-only over the whole
idle window is ever unprotected.

### Exactly one destructive consumer, gated on temp-rooted namespaces

`_evaluate_ephemeral` (`src/vaultspec_rag/storage_ops.py:1224`) is the only
code that turns the stamp into a destruction decision. It considers a namespace
only when it is `live` and `is_temp_rooted(s.root)`
(`src/vaultspec_rag/storage_ops.py:1248`), and it treats a missing or
unparsable stamp as `pending` rather than destroying on absent evidence
(`src/vaultspec_rag/storage_ops.py:1256`). The idle window defaults to 72 hours
(`ReclaimPolicy.ephemeral_idle_hours`, `src/vaultspec_rag/storage_ops.py:1226`),
and a zero or negative value disables the tier outright.

A conventional project root is therefore never a candidate, which is the
strongest single fact in this picture: the defect cannot destroy an operator's
real project data. What it can reach is a temp-rooted namespace - the harness
temp dir the tier exists to reclaim - whose only indexing traffic is document
traffic. There, a run that starts more than 72 idle hours after the last code
or vault run presents an expired clock for its entire duration, and a
maintenance tick landing in that window evaluates `reclaim_data` against a
namespace that is mid-write.

The other consumer is non-destructive: donor candidate ranking sorts siblings
by `last_indexed` (`src/vaultspec_rag/indexer/_donor_candidates.py:420`), so a
never-stamped root simply ranks last as a vector-reuse donor.

### Nothing else advances the clock

Opening a store records the root without a stamp
(`src/vaultspec_rag/store.py:791`), and `record_root` preserves an existing
stamp when the caller supplies an empty one
(`src/vaultspec_rag/storage_manifest.py:383`). The only site that passes a real
timestamp is `touch_manifest_last_indexed` (`src/vaultspec_rag/store.py:817`),
and in server mode alone - the local backend keeps no manifest at all
(`src/vaultspec_rag/store.py:809`). There is no heartbeat, no periodic touch,
and no side effect of ensuring a collection that would have covered the gap.

### The observability loss is unconditional

No structured consumer parses the `service.index` namespace; the events reach
the operator through the managed log tree and the log tail. That makes the loss
simple to state and impossible to dismiss: an operator filtering the log for
index activity sees code runs and vault runs and no document runs at all, on
every root, in both backends. A document pass that runs for an hour, or fails,
leaves no trace on the surface the other two kinds populate.

### The wrapper was four verbatim copies

The accept / lock / stamp / emit / delegate / stamp / emit shape appears
identically at `src/vaultspec_rag/indexer/_codebase_indexer.py` and
`src/vaultspec_rag/indexer/_vault_indexer.py` in both entry points, down to the
comment explaining why the stamp happens at run start. The document indexer
carries the same lifecycle shape without either the stamp or the events. The
divergence is structural rather than accidental: nothing compared the copies,
so the fix that landed in four of them had no mechanism to reach the fifth.

### What was not investigated

Whether the maintenance cycle and a document run can be co-scheduled in one
process such that the race is not merely reachable but likely was not measured;
the finding here is reachability, not frequency. The idle-tier behaviour under
a clock that moves backwards (a manifest restored from a backup) was also not
examined, because nothing in the current write path can produce it.

## Sources

- `src/vaultspec_rag/storage_manifest.py:123`
- `src/vaultspec_rag/storage_manifest.py:349`
- `src/vaultspec_rag/storage_manifest.py:383`
- `src/vaultspec_rag/storage_ops.py:1224`
- `src/vaultspec_rag/storage_ops.py:1226`
- `src/vaultspec_rag/storage_ops.py:1248`
- `src/vaultspec_rag/storage_ops.py:1256`
- `src/vaultspec_rag/store.py:791`
- `src/vaultspec_rag/store.py:809`
- `src/vaultspec_rag/store.py:817`
- `src/vaultspec_rag/indexer/_donor_candidates.py:420`
