---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:84f3f2cd5a381a46a835187dc0ebc8a0c27d6ac43b522f627be2b2505f97da7a'
step_id: 'S13'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# prove the dims and vector-layout gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded

## Scope

- `src/vaultspec_rag/tests/test_donor_candidates.py`

## Description

- Captured the pre-mutation blob hash of `src/vaultspec_rag/indexer/_donor_candidates.py` (`7cf99ce8`).
- Mutated the dims/named-vector-layout comparison in `evaluate_donor_eligibility` so a wrong-dims or wrong-layout donor passes eligibility: the compare `donor_schema != schema` was flipped to `donor_schema == schema`, which stops the gate from appending `VECTOR_LAYOUT_MISMATCH`.
- Ran the binding tests alone: `test_dense_dimensionality_mismatch_is_rejected` (768 vs 1024) and `test_named_vector_layout_mismatch_is_rejected` (sparse present vs absent).
- Restored the `!=` compare, re-hashed the file, and re-ran both tests green.

## Outcome

Guard proven able to fail for the intended reason.

Mutation: in `evaluate_donor_eligibility`, the schema branch changed from

```
elif donor_schema != schema:
    reasons.append(IneligibilityReason.VECTOR_LAYOUT_MISMATCH)
```

to

```
elif donor_schema == schema:
    reasons.append(IneligibilityReason.VECTOR_LAYOUT_MISMATCH)
```

Red (mutation in place), on the intended reasons assertion:

```
>       assert not verdict.eligible
E       assert not True
E        +  where True = DonorEligibility(eligible=True, reasons=()).eligible
```

The wrong-dims (and wrong-layout) donor was declared eligible with an empty reasons tuple - the `VECTOR_LAYOUT_MISMATCH` the test binds to went absent. Both binding tests failed on this assertion.

Green (restored): blob hash back to `7cf99ce8` and `2 passed`.

## Notes

Two tests bind this single gate (dimensionality and named-vector layout); both were driven red by the one mutation and both restored green. Mutation restored in the same uninterrupted sequence.
