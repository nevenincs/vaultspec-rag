---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:95a5e1d897c658b3b8550c5ec005e8b146db947980e17f14bbf3ed3902566529'
step_id: 'S16'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# prove the fragment-id uniqueness guard fails against the pre-fix identity construction and record both directions

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`

## Description

- Mutate `_locator_identity` to the pre-fix shape (fragment ordinal only on the unit-ordinal branch), run the uniqueness guard alone, observe it fail on its intended assertion, restore, observe it pass - one uninterrupted sequence.

## Outcome

RED: `test_locator_bearing_fragments_have_unique_ids` failed on `assert len(set(ids)) == len(ids)` with `AssertionError: assert 1 == 4` (all four fragments of one page collapsed to one id). GREEN: restored construction, test passed alone. The mutation was never left on disk across a pause.

## Notes

An equivalent proof of the same guard was run earlier the same day against the omit-on-locator-branch mutation (RED `assert 1 == 3`, then GREEN) and is recorded in the body of commit `29168706`.
