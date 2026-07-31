---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S02'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Canonicalise the subset before digesting it, excluding the volatile modified stamp by construction and absorbing pure whitespace and quoting churn

## Scope

- `src/vaultspec_rag/_store_models.py`

## Description

- Add `_canonical_metadata()` to `src/vaultspec_rag/_store_models.py`: strip every
  scalar and every list element, then serialise the subset as JSON with sorted
  keys, tight separators, ASCII escaping, and NaN rejected.
- Add `vault_metadata_digest()` over that canonical form, blake2b at 16 bytes.

## Outcome

Churn that changes no value no longer changes the digest. Re-quoting, re-wrapping,
and trailing whitespace are absorbed by the parse plus the strip, so a document
reformatted by the vault check fixer costs nothing.

List order is deliberately preserved rather than sorted. Order is payload-visible,
so a reordered tag list genuinely changes what the store holds; sorting it would
have made a real payload delta invisible, which is the same silent-staleness
failure the subset exists to prevent, only in the opposite direction.

The stamp is excluded by construction and needs no rule of its own.

## Notes

The digest is 16 bytes rather than blake2b's 64. Thirty-two hex characters per
document keeps the sidecar small at corpus scale while leaving collision far
outside anything a vault can reach.

A test asserts every subset member moves the digest on its own, so a field that
canonicalisation quietly folded away could not masquerade as a covered one.
