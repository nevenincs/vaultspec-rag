---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:9db9b034600fb0f90b287d0be345eb70087846db4e36eed1d1c99e3c855bd80e'
step_id: 'S14'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# prove the embedding-model-identity gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded

## Scope

- `src/vaultspec_rag/tests/test_donor_candidates.py`

## Description

- Assessed whether the existing binding test isolates the model-identity scenario precisely: same dims, same content, marker-only mismatch. It does. `test_model_identity_mismatch_is_rejected` writes a donor sidecar with `marker="1"` while the expected embed marker differs, holds the content epoch equal (`epoch-current`), supplies an identical probed vector schema, and matches storage-schema generation and kind. The embed-input format marker is therefore the sole differing field, and eligibility never reads chunk content, so the rejection cannot come from a content miss. No test strengthening was needed.
- Captured the pre-mutation blob hash of `src/vaultspec_rag/indexer/_donor_candidates.py` (`7cf99ce8`).
- Mutated the embed-marker comparison in `evaluate_donor_eligibility` so a mismatched marker is ignored: `state.embed_schema != model.embed_schema` flipped to `state.embed_schema == model.embed_schema`.
- Ran the binding test alone, restored the `!=` compare, re-hashed, re-ran green.

## Outcome

Guard proven able to fail for the intended reason - and, per the precise spec, the red arose from the marker gate itself, not from a content miss (eligibility has no content path).

Mutation: the identity branch changed from

```
if state.embed_schema != model.embed_schema:
    reasons.append(IneligibilityReason.MODEL_IDENTITY_MISMATCH)
```

to

```
if state.embed_schema == model.embed_schema:
    reasons.append(IneligibilityReason.MODEL_IDENTITY_MISMATCH)
```

Red (mutation in place), on the intended reasons assertion:

```
>       assert not verdict.eligible
E       assert not True
E        +  where True = DonorEligibility(eligible=True, reasons=()).eligible
```

The marker-mismatched donor (identical dims, identical epoch, marker-only mismatch) was declared eligible with an empty reasons tuple - the `MODEL_IDENTITY_MISMATCH` the test binds to went absent.

Green (restored): blob hash back to `7cf99ce8` and `1 passed`.

## Notes

Rationale for why this gate matters on its own: the per-point content verification at the encode seam bounds only content staleness (a same-id/different-bytes donor). Model staleness - a donor encoded under a different embed-input format at the same dimensionality with byte-identical content - would sail past the content verify. It rests entirely on this embed-marker gate. Model revision proper is recorded nowhere today; the dims gate catches a revision swap that changes dimensionality, and this marker gate catches an embed-format change, with the content verify covering the residual. No test strengthening was required because the existing test already isolates the marker as the only varying field.
