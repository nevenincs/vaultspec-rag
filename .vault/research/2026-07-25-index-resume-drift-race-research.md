---
tags:
  - '#research'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-23-chunk-id-uniqueness-adr]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #research) and one feature tag.
     Replace index-resume-drift-race with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown [label](path) links in the document body.
     - Cite external sources as bare URLs. Cite code, commits, packages, and
       standards as inline backtick locators: `src/module.py:42`, commit
       `abc1234`, `package@1.2.3`, RFC 9110. -->

<!-- DOCUMENT BOUNDARY:
     Research grounds; the ADR decides. Frame the option space with evidence
     and trade-offs; at most name the option the evidence favors and what
     the ADR must settle. Never record the decision here - a decision
     outside the ADR forks and goes stale when the ADR chooses otherwise. -->

# `index-resume-drift-race` research: `resumed index over a moving tree aborts on the indexed-path upsert guard`

A resumed code-index generation that runs over a tree someone is still editing
can abort the entire run with `cannot add upsert commit units after a path is indexed`. The question is where the window is, how wide it is, and whether it can
be closed at all or only narrowed. The evidence says it cannot be closed by
moving the existing re-open earlier or later, because the re-open must perform
storage I/O and therefore cannot be folded into the ledger transaction that
detects the collision. The option space is consequently about blast radius and
about which layer owns the retry, not about eliminating the race.

This matters because indexing a working tree while a person or an agent edits it
is the ordinary case, not an exotic one, and the current failure mode converts
one racing path into a failed run of every path.

## Findings

### The guard is correct and must stay

`src/vaultspec_rag/indexer/_run_ledger.py:672` refuses an `UPSERT` commit unit
for a path already recorded `INDEXED` with evidence from the same generation.
This is not over-strict. Chunk identity embeds the line span and a content hash,
so re-ingesting changed content mints new point identities rather than
overwriting the old ones; permitting the write would leave both generations'
points live and silently duplicate content. The surrounding ADR constraint is
that a checkpoint may lag storage and replay safely, but must never claim an
unconfirmed mutation. Failing closed is the intended behaviour.

### The existing re-open closes a different window

`src/vaultspec_rag/indexer/_codebase_indexer.py:2826` supersedes resumed
`INDEXED` evidence for paths whose digest changed while the previous attempt was
dead. Its own docstring scopes it to "before any segment is dispatched", and it
is invoked once per run at `src/vaultspec_rag/indexer/_codebase_indexer.py:3599`
and `:3804` over a digest map computed earlier in the same run
(`current_hashes` / `changed_hashes`).

That covers drift that happened *between attempts*. It does not cover drift that
happens *during* the attempt, after the snapshot is taken and before the path's
segments are recorded.

### The window is snapshot-to-record, and it is wide

The sequence that fails:

1. A resumed generation carries `INDEXED` evidence for path P at digest D1.
1. The digest snapshot is taken. P still hashes to D1, so P is not reported
   drifted and is not re-opened.
1. P is rewritten on disk.
1. Chunk and embed read P's new content and produce units at digest D2.
1. `_record_storage_confirmed_unit` finds P `INDEXED` and the unit `UPSERT`, and
   raises.

Step 2 to step 4 spans the whole chunk-and-embed phase for every path ordered
before P, which is the dominant cost of a run. In the observed failure that
phase was scoped at 4535 chunks. The window is therefore not a narrow
instruction-level race; it is most of the run's wall-clock.

### Both preconditions were present in the observed failure

Job `a80047cc` on `vaultspec-rag@0.3.9`, 2026-07-25, indexing a tree with
roughly 710 files under concurrent bulk rewrite:

```
event=reindex_started pending_paths=25 scope=unscoped circuit_state=half_open attempt_generation=460
event=progress        step="chunk + embed" completed=0 total=4535
event=reindex_failed  state=failed error="cannot add upsert commit units after a path is indexed"
```

`circuit_state=half_open` establishes this was a retry, so resumed `INDEXED`
evidence existed; the concurrent rewrite supplies the drift. A non-resumed run
over a moving tree does not reach the guard, because no path carries
same-generation `INDEXED` evidence before its own units are recorded.

### The failure is service-visible and self-sustaining

The run fails wholesale rather than per-path, and the service reports
`Requests: degraded` for as long as the newest indexing job is the failed one.
Because the watcher retries into the same condition while the tree stays busy,
the degraded state can persist across retries rather than clearing on the next
attempt. Observed persisting for 1 hour 53 minutes.

### Why the fix cannot live in the ledger transaction

Re-opening a drifted path is not a metadata edit. The published points must be
dropped from storage first, and only then may the units claiming them be
removed - the ordering is load-bearing, because a point identity may belong to
only one commit unit. Storage I/O cannot be performed inside the SQLite
transaction that detects the collision at
`src/vaultspec_rag/indexer/_run_ledger.py:672`. Any fix therefore reaches the
indexer layer, which is what makes this a design question rather than a
localized guard change.

### Option space

- **Re-check drift immediately before recording a path's units.** Narrows the
  window from whole-run to per-path but does not close it; the file can still
  change between the re-check and the record. Cheap, and strictly better than
  today.
- **Treat the collision as a signal rather than a fault.** Catch the guard at
  the indexer, re-open that path through the existing supersede path, and retry
  just that path. Closes the window by construction because detection and
  remedy use the same evidence, but introduces a retry loop that needs a bound
  against a pathologically hot file.
- **Defer the racing path to the next generation.** Let the run finish without
  it and let the watcher pick it up. Smallest blast radius; leaves the path
  stale for one cycle.

Not investigated: whether the document-index path
(`src/vaultspec_rag/indexer/_document_checkpoint.py`) has the same shape, and
whether the circuit breaker's half-open accounting should treat a drift-induced
failure differently from a genuine fault. Both are open questions for the ADR.

What the ADR must settle: which layer owns detection and remedy, whether the
racing path is retried within the run or deferred to the next generation, and
what bounds the retry if it is retried.

## Sources

- `src/vaultspec_rag/indexer/_run_ledger.py:672` - the indexed-path upsert guard
- `src/vaultspec_rag/indexer/_run_ledger.py:637` - `_record_storage_confirmed_unit`
- `src/vaultspec_rag/indexer/_run_checkpoint.py:211` - `record_confirmed_segments`,
  units recorded then paths marked indexed
- `src/vaultspec_rag/indexer/_run_checkpoint.py:293` - `drifted_indexed_paths`
- `src/vaultspec_rag/indexer/_run_checkpoint.py:315` - `reopen_drifted_path`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:2826` -
  `_reopen_digest_drifted_paths` and its storage-ordering rationale
- `src/vaultspec_rag/indexer/_codebase_indexer.py:3599`, `:3804` - the two
  pre-dispatch invocations
- Service job log for job `a80047cc`, 2026-07-25, `vaultspec-rag@0.3.9`
- https://github.com/nevenincs/vaultspec-rag/issues/262
