---
tags:
  - '#adr'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - "[[2026-07-23-chunk-id-uniqueness-research]]"
---

# `chunk-id-uniqueness` adr: `ordinal-disambiguated chunk identifiers` | (**status:** `accepted`)

## Problem Statement

A code-index update aborts wholesale when one file yields two chunks with an identical identifier, tripping the commit-unit uniqueness invariant before any store write. As grounded in `2026-07-23-chunk-id-uniqueness-research`, the chunk identifier is built from the file path, a line span, and a content hash, and that tuple is not unique when a single oversized line of repeated content is sliced into fixed-width pieces. A decision is needed on how the identifier guarantees uniqueness at construction, so a single minified, base64, SVG, or generated-data file can no longer fail an entire root's index update.

## Considerations

- The uniqueness invariant that raises is correct and stays; the identifier supply must satisfy it (`2026-07-23-chunk-id-uniqueness-research`).
- Two byte-identical slices of one large leaf are distinct content that must both remain indexed; neither may be silently dropped (`2026-07-23-chunk-id-uniqueness-research`).
- One construction path in the same module already disambiguates its identifier by the per-file emit ordinal and never collides; the two defective paths omit it (`2026-07-23-chunk-id-uniqueness-research`).
- Durable-ledger recovery replays upserts by identifier, so a fixed file must produce the same identifiers on re-index; the chunk traversal and split order are deterministic, so a per-file ordinal is stable for unchanged input.

## Considered options

- **De-duplicate chunks before commit-unit assembly.** Rejected: dropping a byte-identical slice discards real content and coverage, and leaves an identifier scheme that still cannot guarantee the invariant one layer up.
- **Widen the content hash (more bytes) or hash the full slice.** Rejected: identical adjacent slices hash identically at any width; a wider hash reduces accidental cross-content collisions but does not address repeated identical text on one line.
- **Disambiguate the identifier by the per-file emit ordinal.** Chosen: makes the identifier unique by construction regardless of span or content, matches the existing in-module preprocess pattern, retains every chunk, and stays deterministic for unchanged files.

## Constraints

- Parent feature `large-index-resilience` owns the commit-unit and durable ledger; this decision changes only identifier construction upstream of it and must not alter the invariant or the replay contract. That parent is accepted and stable.
- The identifier is consumed as a stable point key by the vector store's id derivation; the change must keep identifiers deterministic per file so replayed upserts remain idempotent.
- CPU-only chunk workers construct these identifiers; the change stays within the worker's existing torch-free, store-free construction path.

## Implementation

Every code-chunk identifier gains the chunk's zero-based per-file emit ordinal as a leading discriminator, so two chunks of one file can never share an identifier even when their span and content are identical. Both non-preprocess construction sites - the AST path and the text-splitter fallback path in the chunk worker - adopt the ordinal already used by the preprocess-unit path, making all three construction paths consistent. The ordinal is assigned in emit order, which is deterministic for a fixed file, so re-indexing an unchanged file reproduces the same identifiers and the durable-ledger replay stays idempotent. The commit-unit uniqueness check is left unchanged; it now holds by construction. A guard test drives a repeated-content long line through the real chunker and asserts the emitted identifiers are unique and that a commit unit built from them is accepted, and is shown to fail against the pre-fix construction so the guard is proven to bind.

## Rationale

The ordinal is the only option that makes the invariant hold at the source rather than patching a downstream symptom, and it is already validated in the same module by the preprocess path that has never exhibited this collision (`2026-07-23-chunk-id-uniqueness-research`). It retains all content, unlike de-duplication, and unlike a wider hash it defeats the actual failure mode - identical repeated text on a single line span. Determinism of emit order preserves the idempotent-replay guarantee the durable ledger depends on.

## Consequences

A single pathological file can no longer fail a root's entire code-index update; the dominant deterministic failure mode is removed. Identifiers for such files change shape (they gain an ordinal prefix), so the first re-index after the fix rewrites those chunks' point keys - a one-time churn, not ongoing. Because identifiers already embed a line span they were never content-address-stable across edits, so this adds no new instability. The three chunk-construction paths converge on one identifier convention, reducing the chance a future path reintroduces the omission; a lingering pitfall is that any newly added construction path must adopt the same ordinal, which the guard test and the converged convention make visible.
