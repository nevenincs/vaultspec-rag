---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:669cf58d346e803eed7bbd99652a349f539d72c3746f07fc0572feab59362416'
step_id: 'S03'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Cover the subset definition with a test that fails when a payload field is added without entering the subset digest

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add `src/vaultspec_rag/tests/test_vault_metadata_subset.py`.
- Assert both vault payload builders' key sets are fully covered by the union of
  the subset, the body keys, and the structural keys, failing with the escaped
  field names in the message.
- Assert the subset names nothing the payloads do not carry, that every subset
  member moves the digest alone, that whitespace churn does not, that the body
  does not, and that tag order does.

## Outcome

Seven tests, all passing. The partition assertion is the enforcement: it fails
the moment a payload gains a field that entered neither the subset nor an
explicit body/structural classification.

Proven able to fail, in one uninterrupted sequence: added `"author": "mutation"`
to the vault chunk payload builder, ran the module alone, and watched
`test_chunk_payload_keys_are_all_accounted_for` fail on its own partition
assertion - `vault chunk payload fields outside the subset digest: ['author']` -
not on an import or a collection error. Removed the field; all seven passed again.
No mutation was left on disk.

## Notes

The failure message names the escaped field and states both remedies, because the
next reader will hit this while adding a payload field and needs to be told which
of the three classes it belongs in rather than that something is merely wrong.
