---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-07-27'
body_hash: 'sha256:1fb99c7637bdb79e2d0e77b6b53ca0d3562e921cea4b3dc8edc19f25853150f0'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-2-vault-indexer`

Re-implement `VaultIndexer.full_index` and `VaultIndexer.incremental_index`
to take `reporter: ProgressReporter` as a required keyword argument and
emit phase events around every pipeline step.

- Modified: `src/vaultspec_rag/indexer.py`

## Description

Both entry points gained a required keyword-only `reporter` parameter.
The embed phase now slices `texts` into sub-batches sized against
`get_config().embedding_batch_size` and calls `reporter.advance(len(chunk))`
between slices. Dense and sparse loops are separate phases with
descriptive labels. Each non-embed phase (`scan vault`, `parse documents`,
`hash documents`, `upsert documents`, `delete removed`, `write metadata`)
emits its own `phase_start`/`phase_end` pair. Zero-work shortcuts still
emit empty phases so the reporter stays visible.

The Protocol import lives in the `TYPE_CHECKING` block, keeping
`indexer.py` free of any `rich` import (verified by grep).

## Tests

Compile-verified by the unit suite. Real per-phase validation lands in
phase 6 with the counting integration test.

## Notes

Evidence gap: the retained document body has no separately labelled Notes section.

## Outcome

Evidence gap: the retained document body has no separately labelled Outcome section.
