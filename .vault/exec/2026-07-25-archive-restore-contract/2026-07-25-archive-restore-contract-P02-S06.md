---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:902e2344e4c9d811e0b38ccb321e1637694d1d849ec917994ce5c835dabd6e57'
step_id: 'S06'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Add the archive reader that parses a snapshot manifest and refuses an absent, unparseable, or incomplete archive whole, mutating nothing

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Add the reader that turns an archive directory into a description a restore can act on, and refuses anything short of a complete one. It parses the snapshot manifest, validates every field it will later rely on, and confirms each named snapshot artifact is present and non-empty - before any restore exists to call it.

## Outcome

Delivered as `read_archive` in `src/vaultspec_rag/storage_restore.py`. It parses the snapshot manifest and refuses the archive whole - never a partial read - on an unreadable or non-object manifest, a non-canonical prefix, a missing or non-integer schema generation, an empty or absent collection list, an unparseable completion stamp, an invalid per-collection record, a snapshot filename that is not a bare basename, a repeated collection, an invalid identity payload, and a missing or zero-length snapshot artifact.

Nothing is created and nothing is written: the reader only stats and reads.

The module lives at `storage_restore.py` rather than the `storage_ops.py` the step row names. That module was divided into `storage_survey_ops.py` and siblings before this step ran, and restore is its own responsibility rather than a survey operation.

## Notes

The reader refuses the archive as a whole rather than skipping a bad record and returning the rest. A restore built on a partial read would recover some collections and silently omit others, which is worse than not restoring: the operator would have a namespace that looks complete.
