---
tags:
  - '#adr'
  - '#watcher-targeted-reindex'
date: '2026-06-02'
related:
  - "[[2026-06-02-watcher-targeted-reindex-research]]"
---

# `watcher-targeted-reindex` adr: `watcher targeted reindex contract` | (**status:** `accepted`)

## Problem Statement

Result of investigating issue #151. The resident watcher reacts to every
matched filesystem change by running a full `incremental_index()` pass that
re-scans and re-hashes the entire (ignore-filtered) tree, even though only one
or a few paths changed. Under sustained editing this saturates a CPU thread per
service. The watcher already receives the exact set of changed paths from
`awatch` but discards it. This ADR fixes the indexer/watcher contract so
per-change work is proportional to the change, not to tree size.

## Considerations

- The watcher loop in `watch_and_reindex` already iterates the `(Change, path)`
  set yielded by `awatch`; it classifies vault vs code but then calls the
  argument-less indexer entry point.
- `VaultIndexer` and `CodebaseIndexer` both expose `incremental_index()` whose
  locked body does a whole-tree scan + per-file `blake2b` digest + full Qdrant
  id read. Four production call sites construct `CodebaseIndexer`; signatures
  must stay backward compatible.
- The existing `debounce`/`cooldown`/`watch_enabled` gating (and the pending
  #143/#144 config work) must remain the frequency lever; this change only
  reduces per-run cost.
- Deletions and renames must still be honoured: a targeted pass must remove
  embeddings for paths that were deleted or moved out of scope.
- `.gitignore` + `.vaultragignore` filtering (`2026-04-04-vaultragignore-adr`)
  must still apply to changed paths so an edit to an ignored file is a no-op.
- Testing mandates: real GPU, real Qdrant, no mocks/skips. A targeted-reindex
  test must assert that editing one file embeds exactly that file's chunks and
  leaves the rest of the index untouched.

## Constraints

- No new third-party dependency. `watchfiles`, `pathspec`, `qdrant-client`,
  and the GPU embedding stack are already present and stable.
- Must compose with, not pre-empt, the #143/#144 watcher-config/auto-reindex
  contract, which is owned by the `service-operability` line and remains
  in-flight. This ADR is scoped strictly to the per-change cost.
- The full-scan path must remain reachable and correct for first-time index,
  explicit CLI `index`, and `clean=true` rebuilds.

## Implementation

Add a path-scoped reindex entry point to each indexer — conceptually
`incremental_index(changed_paths=...)` — that, given a concrete set of changed
filesystem paths: filters them through the existing ignore specs and the
vault/code classification, resolves each surviving path to its document id,
re-embeds only added/modified ids, deletes embeddings for removed ids, and
updates only those entries in the persisted hash metadata (read-modify-write of
the existing meta map rather than recomputing it wholesale). When
`changed_paths` is omitted the method keeps its current full-scan semantics, so
existing call sites and the `clean`/first-run paths are unchanged.

`watch_and_reindex` is updated to collect the changed vault paths and changed
code paths it already classifies and pass them into the scoped entry point,
instead of calling the argument-less form. Debounce, cooldown, and the GPU
`gpu_lock`/`_writer_lock` serialisation are retained unchanged.

The detailed call-site signatures, the metadata read-modify-write shape, and
the deletion handling are captured in the implementation plan rather than here.

## Rationale

F1-F4 of `2026-06-02-watcher-targeted-reindex-research` establish that the
saturation is per-change full-tree hashing, not frequency. Option O1 (targeted
reindex from the change set, recommended in the research) makes per-event work
O(changed files); O2 (in-memory hash cache) still walks the tree, and O3
(coarser debounce) is the existing #143 tuning lever, not a fix. Reusing the
change set the watcher already holds keeps the design minimal and additive
(optional argument, full-scan default preserved), which respects the four
existing `CodebaseIndexer` call sites and the inviolable ignore-spec ordering
from `2026-04-04-vaultragignore-adr`.

## Consequences

- Gains: idle-but-edited services stop saturating a thread; per-edit reindex
  latency drops from O(tree) to O(change); reduced contention on the
  single-writer Qdrant lock (#150); the change is additive and backward
  compatible.
- Costs: two reindex code paths (scoped vs full) to keep coherent; the scoped
  path must correctly handle deletes/renames and partial-meta updates, which is
  where correctness bugs would hide — covered by mandated real-GPU tests.
- Pitfalls: a path that changes type or moves across the vault/code boundary
  must be processed by both classifications; the meta read-modify-write must
  not drop ids for unchanged files. These are explicit plan/test items.
- Opens: a future in-memory hash cache (O2) and the #143/#144 configurable
  auto-reindex contract can layer on top without revisiting this decision.

## Codification candidates

None. This decision is local to the watcher-reindex path and does not introduce
a durable cross-session constraint beyond the feature itself.
