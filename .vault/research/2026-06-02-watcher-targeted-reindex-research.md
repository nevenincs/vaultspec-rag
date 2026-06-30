---
tags:
  - '#research'
  - '#watcher-targeted-reindex'
date: '2026-06-02'
modified: '2026-06-30'
related: []
---

# `watcher-targeted-reindex` research: `watcher targeted reindex: per-change cost`

Investigation of GitHub issue #151: resident `vaultspec-rag` watcher processes
saturate a single CPU thread whenever the watched tree is being edited, even
though the operator perceives the service as idle (they are not running
searches). This grounds the symptom against live process profiling and the
current `main` indexer source, isolates the root cause, and surveys fix
options for the execution phase.

## Findings

### F1: The cost is per-change, not an idle spin-loop

A live `python -m vaultspec_rag.mcp_server --port 8766` process (33 threads)
was sampled over several windows. While a concurrent agent was editing `.py`
and `.md` files in the worktree, the process sustained 0.27-0.62 of a CPU core
(consistent with the reported "~one full thread, ~4% on a 24-thread CPU").
Once editing stopped, the identical process fell to 0.002 cores. The CPU is
therefore driven entirely by filesystem-change activity, not by a busy-wait on
nothing.

### F2: py-spy localises the burn to full reindex on every event

An 8-second native py-spy sample (808 samples) of the "idle" process placed
~51% of samples (415/808) on the watcher's AnyIO worker thread executing
`vault_indexer.incremental_index(...)` at `watcher.py:196`, descending into
`_incremental_index_locked`, the `vaultspec_core` scanner's `get_doc_type`,
`pathlib.relative_to`, and content hashing. The watcher is running a complete
reindex pass back-to-back, gated only by the cooldown.

### F3: Root cause — change detection rescans the whole tree

`watch_and_reindex` already holds the concrete change set (it iterates
`changes` yielded by `awatch`), but discards it and calls the argument-less
`incremental_index()`. The locked implementation `_incremental_index_locked`
does a full pass on every invocation regardless of what changed: `scan_vault`
walks the entire vault, `get_doc_type` parses frontmatter of every document,
`store.get_all_ids()` reads all Qdrant ids, and `hashlib.file_digest` hashes
every current document to diff against stored hashes. `CodebaseIndexer`'s
incremental path does the equivalent over every git-tracked source file. So a
single one-line edit forces a rehash of the entire (ignore-filtered) tree.

### F4: Cooldown caps frequency but not per-run cost

The watcher enforces a per-source cooldown (`cooldown: float = 30.0`) and a
debounce (`debounce: int = 2000` ms), tracked independently for vault and code
via `time.monotonic()`. This bounds reindex frequency to roughly one run per
30 s per source, but each run is a full-tree hash. Under a continuous edit
trickle the duty cycle approaches 50-100% of one core; with N worktrees each
running a resident service it is N saturated threads.

### F5: Prior art and scope boundaries

- The `2026-04-04-vaultragignore-adr` decision already narrows *which* files
  are scanned (`.gitignore` + `.vaultragignore`, two-spec OR), and explicitly
  records that "the watcher already re-reads `_scan_codebase()` on every code
  change". That confirms the full-walk-per-event design; it does not address
  the per-event cost, which is this issue.
- The `2026-06-01-service-operability-research` triage covers watcher
  *configurability* (#143) and a first-class opt-out auto-reindex *contract*
  (#144). Those are about exposing/typing the knobs; #151 is the orthogonal
  performance defect of the reindex itself. The fix here should not pre-empt
  #143/#144 design, but must compose with the existing
  `debounce`/`cooldown`/`watch_enabled` surface.
- Issue #150 (single-writer local-file Qdrant lock) is aggravated by this bug:
  every full reindex pass competes for the same writer lock, so reducing
  reindex work also reduces lock contention.

## Options for the fix

### O1: Targeted reindex from the watcher's change set (preferred)

Thread the changed paths from `awatch` into a new indexer entry point that
re-hashes/re-embeds only those documents (and processes deletions for removed
paths), instead of calling the full `incremental_index()`. Keeps the full scan
for first-time, explicit, and `clean` reindex. Largest win: per-event work
becomes O(changed files) instead of O(tree).

### O2: Cache the per-file hash/scan state in memory

Keep the full-scan API but maintain an in-memory `path -> (mtime, hash)` cache
so unchanged files skip the digest read. Reduces I/O but still walks the whole
tree and still O(tree) in stat calls; partial win, more state to keep coherent
with external writers.

### O3: Coarsen debounce/cooldown only

Raise the debounce/cooldown defaults. Reduces frequency, not per-run cost;
makes the index staler without removing the saturation under sustained edits.
Rejected as a primary fix — it is the existing `#143` tuning lever, not a fix.

## Recommendation

Pursue O1 (targeted reindex from the change set) as the core change, preserving
the full-scan path for explicit/clean/first-run indexing and composing with the
existing debounce/cooldown gating. O2's hash cache is a possible follow-on but
not required. O3 is configuration, owned by #143/#144.
