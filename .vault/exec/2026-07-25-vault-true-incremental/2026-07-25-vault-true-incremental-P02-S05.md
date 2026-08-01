---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:ff7acc0826f4d0fea5c061cae033c98b91ba48072521602639bd0b4d0fae654d'
step_id: 'S05'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Persist both digests in the sidecar under the existing meta-versioning convention so an old sidecar is recognised rather than misread

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Encode both digests plus the raw digest into one sidecar value, scheme-tagged:
  `v2|raw|body|metadata`.
- Add `VAULT_FINGERPRINT_SCHEME_KEY` to `src/vaultspec_rag/indexer/_vault_meta.py`
  beside the existing point-schema and content-epoch keys, and stamp it in
  `_write_meta` alongside them.
- Make `parse()` return nothing for a bare digest or a malformed value, so an old
  entry is recognised rather than misread.

## Outcome

The sidecar stays a flat mapping of document id to string, which is what every
existing reader of it expects; widening the value to an object would have broken
them all for information the encoded string already carries.

Recognition happens at two levels, deliberately. Each entry carries its own scheme
tag, which is the authority and makes a partially migrated sidecar safe. The
reserved key is the sidecar's summary of them, used to say once at the top of a
migrating run that the corpus predates the split, so a run that does more work
than its successors is not diagnosed twice.

## Notes

The raw digest is kept in the value permanently rather than dropped after
migration. It is the byte-identity fast path and the only field a legacy entry
can be compared against, and a scheme that discarded it would have made the
migration in S09 impossible to do cheaply.
