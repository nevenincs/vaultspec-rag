---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S15'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# prove the content-epoch gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded

## Scope

- `src/vaultspec_rag/tests/test_donor_candidates.py`

## Description

- Captured the pre-mutation blob hash of `src/vaultspec_rag/indexer/_donor_candidates.py` (`7cf99ce8`).
- Mutated the content-epoch sentinel comparison in `evaluate_donor_eligibility` so a different-epoch donor passes: `state.content_epoch != expected_content_epoch` flipped to `state.content_epoch == expected_content_epoch`.
- Ran the binding test alone: `test_content_epoch_mismatch_is_rejected` (donor stamped `epoch-stale` against expected `epoch-current`).
- Restored the `!=` compare, re-hashed, and re-ran green together with the fail-closed direction test `test_missing_sidecar_fails_closed` to confirm that direction still binds.

## Outcome

Guard proven able to fail for the intended reason.

Mutation: the epoch branch changed from

```
if state.content_epoch != expected_content_epoch:
    reasons.append(IneligibilityReason.CONTENT_EPOCH_MISMATCH)
```

to

```
if state.content_epoch == expected_content_epoch:
    reasons.append(IneligibilityReason.CONTENT_EPOCH_MISMATCH)
```

Red (mutation in place), on the intended reasons assertion:

```
>       assert not verdict.eligible
E       assert not True
E        +  where True = DonorEligibility(eligible=True, reasons=()).eligible
```

The stale-epoch donor was declared eligible with an empty reasons tuple - the `CONTENT_EPOCH_MISMATCH` the test binds to went absent.

Green (restored): blob hash back to `7cf99ce8`; the epoch test and the fail-closed `SIDECAR_UNAVAILABLE` direction both pass (`2 passed`).

## Notes

The fail-closed direction (`test_missing_sidecar_fails_closed`, asserting `SIDECAR_UNAVAILABLE`) was verified to still bind on the restored code - a missing donor sidecar yields ineligible via the sidecar-unavailable reason, independent of the epoch gate. Mutation restored in the same uninterrupted sequence.
