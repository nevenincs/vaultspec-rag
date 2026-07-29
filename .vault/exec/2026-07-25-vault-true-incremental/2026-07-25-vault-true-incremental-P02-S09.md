---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S09'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Hold the first run under the new scheme to a re-classification rather than a re-embed, reusing donor vectors from the root's own collection wherever the body digest matches

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Carry the raw whole-file digest inside every fingerprint as the bridge to the
  previous scheme.
- Compare a legacy sidecar entry against that raw component in `classify()`:
  equal means the bytes never moved, so the document is unchanged and its entry
  migrates by being rewritten.
- Treat a legacy entry whose raw digest differs as a body delta, since the old
  scheme recorded nothing about what moved.
- Announce the migration once per run through `_announce_fingerprint_migration()`.

## Outcome

The first run under the new scheme re-classifies the corpus without re-embedding
it. A document whose bytes have not changed since the last run under the old
scheme is recognised as unchanged from its raw digest alone and re-labelled at
the cost of a parse.

The one-time re-embed is bounded by the documents actually edited since the last
index, not by the corpus. Donor vector reuse remains available underneath and
absorbs part of even that, but the classification does not lean on it - correct
classification stays upstream of reuse, as the decision requires.

## Notes

The bound is honest and pinned by a test: a document that was stamp-churned
*while* the sidecar was still legacy re-embeds once, because the old scheme
cannot distinguish that from a body edit. It is recorded as a test rather than
left to be rediscovered as a suspected classification defect.

Per-entry scheme tags mean a sidecar half-migrated by an interrupted run is
correct, not merely tolerable: each entry is decided on its own tag.
