---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S52'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Re-open a resumed generation's path whose source digest no longer matches the digest recorded when it was marked indexed, superseding its prior units instead of refusing the write

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`
- `src/vaultspec_rag/indexer/_run_checkpoint.py`

## Description

- Add a ledger lookup returning the recorded digest of every named path a
  generation already marked indexed, chunked internally so callers may pass an
  unbounded path set (`src/vaultspec_rag/indexer/_run_ledger.py:1102`).
- Add a ledger re-open that removes one path's superseded upsert units and its
  indexed state inside a single transaction, refusing to act once finalization
  has begun (`src/vaultspec_rag/indexer/_run_ledger.py:1039`).
- Expose both through the code run checkpoint as a drift query and a re-open
  that records durable progress (`src/vaultspec_rag/indexer/_run_checkpoint.py:298`).
- Drop the superseded points from storage and re-open each drifted path before
  any segment is dispatched (`src/vaultspec_rag/indexer/_codebase_indexer.py:2686`).
- Call the re-open from both incremental entry points, scoped to the paths the
  run will re-ingest (`_codebase_indexer.py:3421`, `_codebase_indexer.py:3627`).

## Outcome

A resumed attempt over a moving tree is now an ordinary attempt. The guard that
refused the write is untouched and still refuses it; what changed is that the
inconsistent state it was detecting is repaired before any write is attempted.

The repair runs up front, at resume, rather than at the point the guard fires.
That placement is forced rather than preferred: the refusal happens inside a
ledger write transaction that has no storage handle, so a fix there could clear
the stale state but could never drop the points it describes. It would have
traded a visible outage for silently duplicated content, which is the worse of
the two failures. Up front, the indexer still holds its store and its ordinary
reconciliation machinery.

Deleting those points is not optional, and this was verified rather than
assumed. Chunk identity embeds the line span and a content hash, so re-ingesting
changed content mints new identities and cannot overwrite the old ones. Without
an explicit delete the superseded points would simply persist beside their
replacements.

The deletion is not recorded as a deletion unit, which was the design's one
reversal. A point identity may belong to only one commit unit, so while the
superseded upsert still claims those points nothing else can - the attempt to
record one is refused outright. Once that upsert is removed the ledger holds no
claim on them at all, which is precisely what their removal from storage means,
so the unit would have been redundant even had it been permitted. Dropping it
left the sequence shorter and crash-safe in the same move: an interruption
between the storage delete and the ledger clear replays cleanly, because the
path is still recorded indexed under the old digest and is re-opened again,
finding no points left to drop.

Removing the stale upsert units turned out to be load-bearing beyond tidiness.
Completion evidence is grouped by unit kind and source digest and rejects a kind
appearing under two digests, so leaving the old rows would have blocked the path
from ever reaching indexed again under its new content - converting a hard
failure into a path that silently never converges.

The scoping is the other place this could have gone wrong. The digest map passed
in covers only the paths the run is about to re-ingest. Re-opening any path
beyond that set would delete its points without republishing them, so a
convenience widening here would have been data loss.

The cascade was reproduced directly against a real ledger before and after the
change: an indexed path, a changed digest, the exact refusal from the incident,
then supersession, then the same previously-refused write succeeding and the
path re-indexing under its new digest. Replaying the re-open removes nothing and
reports zero, and the superseded point identity is released rather than
lingering.

## Notes

Scope was held to the code domain. The document checkpoint and indexer share the
same resume model, so the same cascade is very likely reachable there; that was
raised as a scope question and deliberately left as a follow-up rather than
silently widened.

Four integration failures appeared in the modules touched by this Step and none
of them are caused by it. Each was run in isolation and the re-open path emitted
nothing in any of them, so the new code demonstrably does not execute on those
runs. The same path did fire once, in a document admission test that passed,
which is the only positive integration evidence available so far. Establishing
the real cause of the four belongs to the harness operator with the resident
service stopped, since that service was mid-outage during these runs and the
working tree also carries another effort's uncommitted changes to the indexer,
the streaming module, and the store.

Verification here is deliberately partial. The ledger-level behaviour was proven
by direct reproduction and two hundred and thirty-nine unit tests in the
surrounding area pass, but no automated test yet reproduces the cascade end to
end through a real index. That test is a separate Step, and it is the one that
matters: a test asserting only that the guard still fires would have stayed
green throughout the original incident.

The file carrying the entry-point calls also holds another effort's uncommitted
work, roughly twelve hundred lines away from any line touched here. There is no
textual overlap, but staging that file wholesale would sweep their changes into
this commit, so it must be staged hunk by hunk.
