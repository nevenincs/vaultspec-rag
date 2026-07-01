---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Write a per-chunk domain payload at code index time, add domain to the code KEYWORD index set ensuring the index idempotently on existing collections, and exclude nested worktree clone dirs from the scan

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add `domain: str` to the `CodeChunkPayload` TypedDict and `"domain"` to
  `CODE_KEYWORD_INDEXES` (additive; no schema-version bump - the compatibility
  gate ignores index/payload-field additions).
- Populate the field in `_code_chunk_payload` via `classify_domain(chunk.path)`,
  so the stored label and the query-time fallback share one source.
- Refactor `ensure_code_table` to extract `_ensure_code_indexes` and run it even
  when the collection already exists, so a newly added KEYWORD index (`domain`)
  backfills on the next open instead of needing a drop-and-reindex.
- Exclude `.claude/worktrees/` agent clone trees from the codebase scan.
- Tests: payload-derives-domain parity test, worktree-exclusion scan test.

## Outcome

`pytest` over the schema parity/drift, schema, and indexer-exclusion suites ->
29 passed. The live-Qdrant drift tests confirm a fresh code collection builds
the `domain` index, and the golden payload now carries the classified domain.

## Notes

The `domain` field is additive; pre-existing chunks lack it until re-upserted.
The query-time path (later Steps) classifies `result.path` as a fallback, so the
feature works before a backfill and gains pushdown after it. Verification does a
clean code reindex so the live collection is fully backfilled.
