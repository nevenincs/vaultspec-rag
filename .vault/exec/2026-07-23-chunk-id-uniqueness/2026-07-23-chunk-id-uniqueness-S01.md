---
tags:
  - '#exec'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S01'
related:
  - "[[2026-07-23-chunk-id-uniqueness-plan]]"
---

# Add the zero-based per-file emit ordinal as a leading discriminator to the AST-path chunk identifier so byte-identical slices of one line cannot collide

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Changed the AST chunk loop in `chunk_with_ast` to `enumerate` its source chunks, binding the per-file emit ordinal as `index`.
- Inserted `index` into the identifier as `f"{rel_path}:{index}:{line_start}-{line_end}:{chunk_hash}"`, making the identifier unique by construction even when a repeated-content line splits into byte-identical slices sharing one line span.
- Added a short comment stating why the ordinal is required (the span-plus-hash form alone cannot distinguish identical slices).

## Outcome

The AST path now emits a unique identifier per chunk regardless of span or content. Verified against the reproduction: a 6000-character repeated-content line that previously yielded 6 chunks with 3 distinct identifiers now yields 6 distinct identifiers, and a commit unit built from them is accepted. Determinism preserved: the serial-versus-pool identity parity test still passes, so search results remain independent of worker count.

## Notes

The identifier is opaque downstream: it is stored verbatim in the `chunk_id` payload field and read back for stale deletion; nothing parses it into a line span (`line_start`/`line_end` are separate payload fields), so the shape change is safe. One-time consequence: files with such lines get new point keys on the first re-index after the fix.
