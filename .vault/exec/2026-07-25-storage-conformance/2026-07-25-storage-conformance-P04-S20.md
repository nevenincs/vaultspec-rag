---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:352cb01d9096f03171180d14bd4e983d6c7dd70e92c7ee811f0a4360f92a79b3'
step_id: 'S20'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Cover the copy carry and the reclamation exclusion with guard tests, and prove each fails when its carry is reverted

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

Add nine guards over the copy carry, the archive record, and the reclamation
exclusion, then observe each failing for the reason it names before trusting it.

## Outcome

Nine guards, ten mutation proofs. Every one was applied, observed failing on the
assertion its own docstring names, restored, and re-run green - each as one
uninterrupted sequence, with the restore verified byte-for-byte before the green
run and no mutation ever left on disk.

Copy carry, at the unit tier:

- Restamping the destination with current values instead of the loaded source
  identity. Failed on the model assertion, reporting the real configured model
  against the fabricated superseded one. This is why the fixtures name a model no
  running configuration would ever produce - a restamp cannot accidentally
  satisfy the assertion.
- Writing both directions into one home. Failed on the carried-name assertion for
  the server-to-local direction.
- Falling back to current values when the source carries no stamp. Failed on the
  empty-carry assertion.
- Ignoring the migrate results and carrying every mapped pair. Failed on the
  empty-carry assertion for a skipped copy.

Archive record:

- Omitting the identity field from the serialized payload. Failed on the
  membership assertion at the unit tier and on the presence assertion at the
  integration tier.
- Substituting a current identity for an absent one. Failed on the explicit-null
  assertion.

Reclamation exclusion, both directions in one test:

- Gating a reclaim on the namespace carrying a stamped model. Failed on the
  reclaimable assertion.
- Admitting a namespace whose root could not be confirmed absent. Failed on the
  empty-decision assertion.

End to end, against a real server: the archive populating identity from the live
manifest, and the copy-then-carry composing over genuinely remapped collection
names. The second was mutated to record under the source name and failed on the
carried-target assertion, which is the specific failure the carry exists to close.

Two proofs were rejected on first pass and the tests tightened rather than
accepted. The archive guards initially failed on a `KeyError` and a `TypeError`
from reading a dropped field, which reads as a broken test rather than a lost
record; both now assert presence before reading, and both were re-proven landing
on that assertion.

## Notes

Every fixture writes its identity sidecar to an explicit temp directory and the
manifest resolves under the isolated managed directory, so no test here touches
the operator's real storage or contends for the machine lock.
