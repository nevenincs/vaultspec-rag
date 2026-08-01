---
tags:
  - '#research'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:0c233bc6877469bbac1bca5f07c62945edf6ba0764053b77e96acd0dfe6917d3'
related: []
---

# `chunk-id-uniqueness` research: `code chunk id collisions on repeated-content long lines`

Background code-index jobs fail hard with `point_ids must be unique within a commit unit`, aborting an entire code-index update for a root. The message is raised by our own commit-unit validation, not by the vector store. The question is how two code chunks acquire an identical identifier within one file, and what identifier construction would make a collision impossible. The evidence shows a deterministic collision whenever a single oversized line of repeated-content is split into fixed-width slices, and that one chunk-construction path in the same module already avoids it by construction.

## Findings

### The rejection is a local uniqueness invariant, not a store error

The commit unit assembled for a file segment validates its identifiers in `src/vaultspec_rag/indexer/_run_ledger.py:255`: `if len(set(self.point_ids)) != len(self.point_ids): raise ValueError("point_ids must be unique within a commit unit")`. The point ids come straight from the file's chunk ids - `point_ids=tuple(chunk.id for chunk in segment.chunks)` in `src/vaultspec_rag/indexer/_run_checkpoint.py:178`. So a single duplicate chunk id inside one file's segment raises before any store call, and the exception propagates as a whole-job failure. The invariant is correct; the identifier supply violates it.

### Chunk ids are derived from span plus a content hash, which is not unique

Both non-preprocess construction sites build the id as `f"{rel_path}:{line_start}-{line_end}:{chunk_hash}"`, where `chunk_hash` is a 6-byte BLAKE2b of the chunk text: the AST path at `src/vaultspec_rag/indexer/_chunk_worker.py:1278` and the text-splitter path at `src/vaultspec_rag/indexer/_chunk_worker.py:1330`. This id is unique only if `(rel_path, line_start, line_end, text)` is unique across a file's chunks. That assumption fails for repeated content on one line.

### `_split_large_leaf` produces byte-identical slices on one line range

An oversized childless AST node is split into fixed 1500-character slices by `src/vaultspec_rag/indexer/_ast_chunker.py:154`. Its line cursor advances by newline count only: `le = ls + chunk.count("\n"); line_cursor = le`. A slice containing no newline leaves `le == ls` and does not advance the cursor, so every slice of a single long line shares one `(line_start, line_end)`. When that line is repeated content - a minified bundle, an embedded base64 blob, SVG path data, a generated data literal, a long run of a repeated delimiter - adjacent 1500-char slices are byte-identical, so `chunk_hash` matches too and the full id collides. The text-splitter fallback path collides the same way: `content.find(text, search_offset)` advances the offset past the first occurrence, but for a no-newline line the recomputed `line_start`/`line_end` are identical and the text is identical, yielding the same id.

### Reproduction (deterministic, CPU-only)

Calling `chunk_with_ast` on a single Python line assigning a 6000-character string of one repeated character produced 6 chunks with only 3 distinct ids (one id repeated four times), and constructing a `CommitUnit` from them raised the exact production error. No GPU, model, or store was involved - the collision is purely in chunk-id construction, so it recurs whenever such a file is indexed.

### One sibling path already disambiguates by ordinal

The preprocess-unit construction in the same module builds `id=f"{rel_path}::pp:{index}:{chunk_hash}"` at `src/vaultspec_rag/indexer/_chunk_worker.py:249`, where `index` is the `enumerate` ordinal of the emitted unit (`_chunk_worker.py:234`). Including the emit ordinal makes that id unique by construction regardless of span or content. The AST and splitter paths omit this ordinal. This establishes both the existing in-module pattern and the shape the fix should take.

### Option space and stability considerations

The collision can be removed at the identifier (make the id unique by construction) or by de-duplicating chunks before commit-unit assembly. De-duplication is wrong: two byte-identical slices of a large leaf are distinct content the searcher should retain, so dropping one loses coverage; and the commit-unit invariant would still be one layer downstream of an id scheme that cannot guarantee it. Disambiguating the id by the per-file emit ordinal (the preprocess pattern) makes the invariant hold at the source. A consideration the ADR must settle is id stability across re-indexing: the id already embeds `line_start-line_end`, so it is not content-address-stable across edits today, and appending an ordinal does not worsen that - but the ADR should state the ordinal is deterministic for a fixed file (the traversal and split order are deterministic) so replayed upserts of an unchanged file remain idempotent, which the durable-ledger recovery contract depends on.

### Not investigated

Whether any currently-indexed production file already carries such a collision (would require reading the live corpus; out of scope and the fix is corpus-independent). Whether vault or document chunk ids share the defect - those ids derive from `doc_id#c{ordinal}` shapes that already carry an ordinal, so they are out of scope here.

## Sources

- `src/vaultspec_rag/indexer/_run_ledger.py:255` - commit-unit uniqueness invariant
- `src/vaultspec_rag/indexer/_run_checkpoint.py:178` - segment point ids sourced from chunk ids
- `src/vaultspec_rag/indexer/_chunk_worker.py:1278` - AST-path chunk id construction
- `src/vaultspec_rag/indexer/_chunk_worker.py:1330` - splitter-path chunk id construction
- `src/vaultspec_rag/indexer/_chunk_worker.py:249` - preprocess path ordinal-disambiguated id
- `src/vaultspec_rag/indexer/_ast_chunker.py:154` - `_split_large_leaf` fixed-width slicing
