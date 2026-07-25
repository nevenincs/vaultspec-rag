---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Persist the point count a code-index publication actually wrote as a reserved metadata key alongside the existing bookkeeping keys

## Scope

- `src/vaultspec_rag/_index_breadth.py`
- `src/vaultspec_rag/indexer/_code_meta.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add `src/vaultspec_rag/_index_breadth.py` as the neutral leaf owning the
  reserved sidecar key and the parse of the point count it carries.
- Stream the published point count into the sidecar's reserved block in
  `publish_meta_from_file_states`, rejecting a negative figure.
- Thread the count through `CodeRunCheckpoint.publish_metadata` and stamp it in
  the atomic writer `CodebaseIndexer._write_meta`.
- Take the count from `store.count_code()` after storage reconciliation at all
  four publication sites: the resume path, both incremental branches, and the
  clean-rebuild path.

## Outcome

Landed in `00ab3ef3`. Every code-index publication this build performs now
records the breadth its sidecar describes.

The claim lives in its own top-level module rather than inside the indexer
package because the search path that reads it must stay importable on a host
with no GPU, and the indexer package pulls in tree-sitter and the torch loader.

Two deviations from the authorising documents, both deliberate:

- **Only the point count is persisted, not a file count.** The plan row and the
  ADR implementation note both named a file count as well. It has no consumer:
  the predicate compares points, and the claimed file count is already exactly
  the number of non-reserved entries in the same sidecar, so a second copy
  could only drift from the entries it counts. The Step row was corrected
  through the owning verb to match what landed.
- **`_write_meta` takes the count as an optional argument.** Its one production
  caller always supplies it; the option exists because a sidecar silent on
  breadth is a first-class state the ADR requires (roots written by an older
  build), and callers with no reconciled count must leave it silent rather than
  stamp a figure nothing verified.

## Notes

`src/vaultspec_rag/indexer/_codebase_indexer.py` was being refactored
concurrently by another worker, which extracted the shared index-run lifecycle
out of the indexers. The two changes do not overlap textually. To avoid
committing unfinished work belonging to someone else, this Step's commit staged
a constructed blob for that file - the committed base plus only this feature's
hunks - leaving the other worker's changes intact and unstaged in the working
tree.
