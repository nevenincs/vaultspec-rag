---
tags:
  - '#plan'
  - '#watcher-targeted-reindex'
date: '2026-06-02'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-02-watcher-targeted-reindex-adr]]'
  - '[[2026-06-02-watcher-targeted-reindex-research]]'
---

<!-- RETIRED: P04 -->

# `watcher-targeted-reindex` `watcher targeted reindex` plan

## Description

Implements `2026-06-02-watcher-targeted-reindex-adr` (decision accepted),
grounded in `2026-06-02-watcher-targeted-reindex-research`, to resolve issue
#151. The watcher currently triggers a full-tree rescan-and-rehash on every
matched filesystem change; this plan makes per-change reindex work proportional
to the change set the watcher already holds. P01 adds an optional
`changed_paths` entry point to both indexers (full-scan default preserved for
first-run/explicit/clean). P02 wires the watcher to pass its classified change
set and proves correctness with real-GPU tests, then gates on lint and the full
suite. Composes with - does not pre-empt - the #143/#144 watcher-config /
auto-reindex contract, and reuses the inviolable `.gitignore` plus
`.vaultragignore` ordering from `2026-04-04-vaultragignore-adr`.

## Steps

### Phase `P01` - scoped reindex in indexers

Add an optional changed-paths entry point to VaultIndexer and CodebaseIndexer
that re-embeds only changed ids, deletes removed ids, and does a partial
metadata read-modify-write; full-scan default preserved.

- [x] `P01.S01` - Add optional `changed_paths` to VaultIndexer.incremental_index with a scoped locked path that classify-and-ignore-filters paths, resolves doc ids, re-embeds added or modified ids, deletes removed ids, and does a partial meta read-modify-write; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `P01.S02` - Add the same `changed_paths` scoped path to CodebaseIndexer.incremental_index honouring gitignore and vaultragignore and handling deletions, keeping the four existing call sites backward compatible; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - wire watcher and verify

Pass the watcher's classified change set into the scoped entry points and prove
correctness with real-GPU tests plus lint and the full suite.

- [x] `P02.S03` - Collect the classified changed vault and code paths in watch_and_reindex and pass them to the scoped reindex entry points, retaining debounce, cooldown, and gpu_lock; `src/vaultspec_rag/watcher.py`.
- [x] `P02.S04` - Add real-GPU tests proving a single-file edit re-embeds only that file, a deletion removes only its chunks, and an ignored-file edit is a no-op, with no mocks or skips; `src/vaultspec_rag/tests/integration/`.
- [x] `P02.S05` - Run ruff and the full pytest suite and confirm zero violations and green before PR; `pyproject.toml`.

### Phase `P03` - idle-tick flush for cooldown-suppressed reindex

Restore the trailing-edge flush so a change suppressed by the per-source cooldown is reconciled on a quiet tree, evicting deleted files without a full rebuild (#192). Construct the watcher's awatch with an idle yield and re-drain the pending sets on every iteration, guarded by the unchanged cooldown.

- [x] `P03.S06` - Construct the watcher's awatch with yield_on_timeout=True and an explicit one-second rust_timeout, and re-drain the pending vault and code sets on every loop iteration so an empty idle-tick batch reconciles cooldown-suppressed changes while the unchanged per-source cooldown guard still gates the actual reindex; `src/vaultspec_rag/watcher.py`.
- [x] `P03.S07` - Add a real-backend watcher regression test that deletes a tracked file during the cooldown window then leaves the tree quiet and asserts the chunks are evicted, plus a guard that an idle tick during an open cooldown does not trigger a premature reindex, folding in the reproduction scenarios and exercising the real backend with no mocks or skips; `src/vaultspec_rag/tests/integration/`.
- [x] `P03.S08` - Run ruff and the full pytest suite and confirm zero violations and green before PR; `pyproject.toml`.

## Parallelization

P01.S01 (vault) and P01.S02 (code) are independent and may proceed in parallel.
P02.S03 (watcher wiring) depends on both P01 steps. P02.S04 (tests) depends on
P02.S03. P02.S05 (lint plus full suite) is the final gate after all other steps.

P03 is a later, self-contained increment that builds on the shipped P01/P02 work.
P03.S06 (the watcher idle-tick change) comes first; P03.S07 (regression test)
depends on S06; P03.S08 (lint plus full suite) is the final gate after both.

## Verification

- A targeted reindex of one changed vault doc embeds exactly that doc's chunks
  and leaves every other id's vectors and hash-metadata entry untouched
  (asserted against real Qdrant plus real GPU).
- Deleting a tracked file via the scoped path removes only that file's chunks
  and its metadata entry; no other ids are affected.
- An edit to a gitignore or vaultragignore-excluded file is a no-op (no
  embedding, no metadata change).
- Existing call sites that invoke `incremental_index()` with no arguments
  retain full-scan behaviour (backward compatibility test green).
- `ruff` reports zero violations and the full `vaultspec-rag test` suite is
  green.
- Manual check: a watcher driven by a single-file edit no longer sustains a CPU
  core; per-edit reindex work is O(change), not O(tree).
- A file deleted during the per-source cooldown window, with the tree then left
  quiet, has its chunks evicted by the watcher without any further filesystem
  event and without a full rebuild (asserted against the real backend).
- An idle tick that fires while the cooldown window is still open does not
  trigger a reindex before the window elapses (the cooldown guard still holds).
- Watcher shutdown via the stop event stays responsive with the idle yield
  enabled (no regression in stop latency).

The plan is complete when every Step in every Phase is closed (`- [x]`).
