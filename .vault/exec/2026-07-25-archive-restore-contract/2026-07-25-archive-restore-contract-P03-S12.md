---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-08-25'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:4eb8e0ffb88ae83dd5d9616122d9a419091582f6e3362105167b9a72875ebb5b'
step_id: 'S12'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Add the end-to-end round trip against a real supervised server: index a root, archive it, drop the namespace, restore under a fresh root, and assert the restored namespace answers a search with the results the original gave, with the Qdrant storage-dir environment variable pointed at a temp path

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py`

## Description

- Add a query vector and three points whose bodies are distinguishable and
  whose cosine ranks against it are fixed, so a reordered or payload-stripped
  recovery fails on content rather than on arity.
- Create the source collection with a named `dense` vector, matching the shape
  production addresses with `using="dense"` rather than the default unnamed one.
- Answer the query before archiving and assert the expected rank order, so the
  comparison is anchored to a checked baseline rather than to whatever the
  source happened to return.
- Archive the namespace, delete the collection, drop the prefix, and assert the
  source no longer exists before restoring.
- Restore under a fresh destination root and require the same query to return
  the same bodies in the same order.

## Outcome

The round trip is covered against a real supervised server. The three cases
that already existed assert only that the destination holds one point, which
cannot separate a faithful restore from one that recovered the collection while
dropping its payloads or leaving its vectors unindexed; this case fails in both
of those directions.

Both directions of the guard were observed in one uninterrupted sequence.
Reversing the expected rank order failed on the pre-archive search assertion,
naming the index-0 difference. Changing the platform-refusal branch to expect a
restore failed on `'refused' == 'restored'`. Restoring each mutation returned
the module to four passing cases; no mutation was left on disk.

## Notes

Three deviations are worth recording.

The Step names a new module, but the case was added to the existing real-Qdrant
restore module instead. That module already owns the supervised-server fixture,
the binary fixture, and the archive helper this case needs; a second module
would have duplicated all three across a seam, which the project forbids.

The restore primitive refuses outright on Windows, so on this host the case
exercises the documented platform refusal and asserts the destination is
neither created nor recorded. The comparison of restored search results against
the original is real but runs only where the primitive does. The mutation proof
covers what executes here: the pre-archive search assertion and the refusal
branch.

Running the case at all required a resident service whose version matches the
working tree exactly, because the tier borrows the device through the machine
pointer. The host's service was a newer release serving an unrelated project,
which the compatibility check rejects. It was swapped for one started from this
tree for the run, and the original returned afterwards.
