---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S12'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# prove the content-verify guard test can fail: mutate the verify to accept mismatched payload content, observe the intended assertion go red, restore, observe green

## Scope

- `record both directions in the Step Record`
- `src/vaultspec_rag/tests/test_index_reuse.py`

## Description

- Captured the pre-mutation blob hash of `src/vaultspec_rag/indexer/_reuse.py` (`2eb8507e`) and confirmed the reuse suite green (34 passed) before mutating.
- Mutated the per-point payload-content verify in `adopt_verified_vectors` so mismatched stored bytes are accepted instead of rejected: the compare `payload_content != identities[index][1]` was flipped to `payload_content == identities[index][1]`, which stops the guard from treating a same-id/different-bytes donor as a miss.
- Ran the binding test alone: `test_content_mismatch_at_same_point_id_is_a_miss_and_encodes`.
- Restored the `!=` compare, re-hashed the file, and re-ran the test green.

## Outcome

Guard proven able to fail for the intended reason. Both directions recorded below.

Mutation (unified sense): in `adopt_verified_vectors`, the content-verify branch changed from

```
or payload_content != identities[index][1]
```

to

```
or payload_content == identities[index][1]
```

Red (mutation in place), on the intended assertion `assert context.stats.reuse_hits == 0`:

```
>       assert context.stats.reuse_hits == 0
E       AssertionError: assert 1 == 0
E        +  where 1 = ReuseStats(reuse_hits=1, reuse_misses=0, ...).reuse_hits
```

The stale donor vector was adopted for the changed chunk (hits 1, misses 0) exactly as the guard is meant to prevent - the intended failure mode, not an incidental error.

Green (restored): blob hash back to `2eb8507e` (byte-identical to pre-mutation) and `1 passed`.

## Notes

A prior in-implementation proof of this guard existed; this is a clean, uninterrupted re-run recorded here. The mutation was restored immediately in the same sequence; no weakened guard was left on disk across any pause.
