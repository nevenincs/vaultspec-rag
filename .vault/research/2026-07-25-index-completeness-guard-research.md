---
tags:
  - '#research'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-27'
related:
  - "[[2026-07-25-index-resume-drift-race-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
---
# `index-completeness-guard` research: a partially destroyed code collection publishes itself as complete

## Findings

### Problem

A root's code index can collapse so that every query resolves to a handful of
files - in the worst observed case one - while search keeps answering normally:
well-formed results, a plausible indexed-section count, no error. The failure is
indistinguishable from a genuine "no such behaviour here" answer.

The cost is not ordinary retrieval noise. Semantic search is the mandated
grounding step before code is written, so a silent false negative to "does an
implementation of this already exist?" is the mechanism by which duplicate
implementations get written.

### Method

Ground truth was read from the store directly rather than through search, so the
measurement does not inherit the defect under investigation: a read-only client
scrolled the root's code collection counting points, distinct payload paths, and
dense-vector degeneracy, and the result was compared against the file set the
published metadata sidecar claims.

### The collection is genuinely truncated; retrieval is innocent

At the time of measurement the root's code collection held **302 points across 5
distinct paths**, against **421 files claimed by the published metadata
sidecar**. All 302 dense vectors were distinct and none was degenerate or
absent.

Retrieval was therefore working correctly over roughly one percent of the
corpus. Two hypotheses are eliminated outright:

- **Ranking pathology is not the cause.** The vectors are healthy and the
  ranking over them is correct; there is simply almost nothing to rank.
- **The count is not read from a different source than the vectors.** Both
  resolve to the same live collection - `count_code` reaches
  `_count_collection` in `src/vaultspec_rag/store.py:1663`, and the search entry
  point takes its `indexed_count` from that same call at
  `src/vaultspec_rag/api.py:605`. The "plausible" count was never a stale
  counter; a partially repopulated collection simply yields a plausible-looking
  number.

The 5 surviving paths were the files most recently rewritten in the working
tree, which is why successive sightings collapsed onto different files.

### An ordinary update job escalates itself to a destructive rebuild

A clean rebuild drops the collection up front and then repopulates it
(`src/vaultspec_rag/indexer/_codebase_indexer.py:2618`). The truncation window
is deliberate and documented in that block.

What makes it reachable without operator action is that an *incremental* run
escalates itself to `clean=True` on embedding-format drift
(`src/vaultspec_rag/indexer/_codebase_indexer.py:2833`) or content-shaping
config drift (`:2851`). A watcher-driven update is therefore sufficient to drop
the collection. This resolves the reported observation that no operator-run code
index job preceded a collapse: the job existed and was automatic.

### A failed run leaves the truncation published as complete

The run then fails part-way. The service job history for this root recorded ten
consecutive code-index failures across several distinct causes - GPU safety
ceiling, no storage-confirmed progress before deadline, the indexed-path upsert
collision, and a missing-file `OSError`. The collection retains only what was
written before the abort.

The metadata sidecar continues to describe the full 421-file corpus, so the
index self-reports complete.

### The truncation is self-confirming and never heals

Every later incremental run diffs the tree against that metadata, classifies
every surviving file as unchanged, encodes nothing, and publishes a successful
result. The index cannot recover on its own; only a rebuild, which ignores the
carried evidence, restores breadth. This matches the reported behaviour exactly,
including that a rebuild reliably fixed it.

### The guard that exists defends only against total destruction

`_published_evidence_lost` at
`src/vaultspec_rag/indexer/_codebase_indexer.py:1647` was written for precisely
this failure. Its docstring names the symptom - carried metadata classifying
every surviving file as unchanged and publishing a successful result over points
that no longer exist.

Its predicate is:

```
bool(self._load_meta()) and not self.store.code_collection_exists()
```

The question it asks is *does the collection exist*. The risk is *does the
collection hold what the metadata claims*. A collection holding 302 of some
thousands of points exists, so the guard returns false and execution takes the
exact path the docstring warns against.

Because a clean rebuild drops and then incrementally repopulates, **every
interrupted clean rebuild lands in the undefended middle** between "intact" and
"absent". The common case is the unguarded one.

### Search has no completeness signal

The search path distinguishes only empty from non-empty
(`src/vaultspec_rag/api.py:605`). It has no access to, and does not consult, the
index generation state that `status` already renders. A partial index is
therefore free to answer confidently, which is what converts a data-loss bug
into a silent correctness bug for the caller.

### Implications

Two defects compound and both need addressing:

- **Permanence.** A completeness predicate that compares stored breadth against
  claimed breadth would escalate a partially destroyed collection to full
  reconciliation, letting the index self-heal instead of latching.
- **Silence.** A search-time completeness signal is required independently: no
  reconciliation can be instantaneous, so the window where an index is
  legitimately incomplete will always exist and must never answer silently.

The destructive drop is the deeper cause and a build-then-swap publication would
remove the window entirely, but it touches the storage layer and the per-root
collection-prefix scheme, and it is not required to stop the silent false
negative.

### Relationship to adjacent work

The indexed-path upsert collision is one of the triggers that leaves a
collection truncated, and it is separately owned by
`2026-07-25-index-resume-drift-race-adr`, which seams the indexer and gives
drift a single owner. That work addresses why runs abort. It does not address
what an aborted run leaves behind, nor that the remains are published as
complete, so the two are complementary rather than duplicative.

### Open questions

- Whether the vault and document indexers carry the same binary-predicate hole,
  and whether their search surfaces have completeness signals.
- How many other roots on this machine are currently latched in a truncated
  state, given the failure is silent and self-confirming.
- Whether a cheap distinct-path count is available through a payload facet
  query, so the completeness predicate does not pay a full scroll on every
  incremental run.

## Sources

Evidence gap: the retained research body has no separately labelled Sources section.
