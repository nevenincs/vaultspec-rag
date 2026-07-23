---
tags:
  - '#exec'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S03'
related:
  - "[[2026-07-23-chunk-id-uniqueness-plan]]"
---

# Add a guard test that chunks a repeated-content over-budget line through the real chunker, asserts unique identifiers and commit-unit acceptance, and record it failing against the pre-fix construction then passing after

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`

## Description

- Added `TestChunkIdentityUniqueness` with two tests that write a real source file whose body is a single 6000-character line of one repeated character (an oversized childless leaf routed through the large-leaf splitter) and chunk it through the real worker `chunk_file` - no GPU, model, store, or mock.
- `test_repeated_content_long_line_yields_unique_ids` asserts more than one chunk is produced and every identifier is distinct.
- `test_repeated_content_chunks_form_valid_commit_unit` builds a real `CommitUnit` from the chunk identifiers and asserts the uniqueness invariant - the exact check that failed in production - accepts them.
- Documented in a class docstring that the assertions bind to the emit-ordinal discriminator and name the mutation they catch (removing the ordinal).

## Outcome

Guard verified in both directions as one uninterrupted sequence, per the guard-test obligation:

- WITH FIX: both tests pass.
- MUTATED (emit ordinal removed from both identifier constructions): both tests fail on the intended assertions specifically - `test_repeated_content_long_line_yields_unique_ids` fails on `AssertionError: duplicate chunk ids: ['generated_blob.py:1-1:f2673e14b205', 'generated_blob.py:1-1:df216b30b144', 'generated_blob.py:1-1:df216b30b144', ...]` (3 distinct of 6), and `test_repeated_content_chunks_form_valid_commit_unit` fails on `ValueError: point_ids must be unique within a commit unit` raised from the commit-unit validation. Neither failed on an incidental error.
- RESTORED: both tests pass again.

This demonstrates the tests are reachable, bind to the uniqueness property they name, and would catch a regression that dropped the ordinal.

## Notes

The mutation was applied and reverted in one sequence with no pause or handoff; the working tree was left with the fix in place and the tests green.
