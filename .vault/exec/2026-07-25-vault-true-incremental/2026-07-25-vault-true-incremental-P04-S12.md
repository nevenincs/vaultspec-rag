---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:d86ddcf79ddf5c100140070dc86c973e9821262d38fb5c05e9bce1361261aa75'
step_id: 'S12'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Prove the stamp-only guard bidirectionally: assert zero encodes on a modified-stamp bump, weaken the fingerprint back to a raw-file digest, watch the encode assertion fail, restore, watch it pass

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add `TestStampOnlyChangeIsFree` to
  `src/vaultspec_rag/tests/integration/test_vault_true_incremental.py`, over a
  real GPU and a real store.
- Assert a stamp bump across the whole corpus yields `updated == 0`,
  `payload_updated == 0`, and vectors byte-identical to before.
- Assert separately that the sidecar entry still moves.
- Drive it red by mutation, restore, drive it green.

## Outcome

Proven able to fail, in one uninterrupted sequence. Weakened
`fingerprint_text()` to return the raw whole-file digest instead of the encoded
split, ran the guard alone, and watched it fail on its own encode assertion -
`a modified-stamp bump re-embedded documents`, `assert 6 == 0` - not on an import
or a collection error. Restored the split; the guard passed again. No mutation
was left on disk.

The mutation is recorded verbatim in the test's docstring, so the next reader can
repeat it instead of loosening an assertion whose narrowness looks accidental.

## Notes

The zero-encode claim is asserted through `IndexResult.updated` plus vector
byte-identity, both production-observable, rather than by instrumenting the
embedding model. Counting encodes through a wrapper would have meant the guard
proved something about a test double; these two assertions together cannot pass
while an encode has happened.

The stamp helper writes with newline translation disabled. The default rewrites
every line ending on this platform, and a "only the stamp moved" guard that
silently reflowed the whole document would have been testing something else.
