---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S18'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Record the stamped identity in the archive snapshot manifest so a restore can be judged

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

Add per-collection identity to the archive snapshot record and its serialization,
and populate it from the live manifest when a namespace is archived.

## Outcome

`SnapshotCollection` gains an optional identity, written into the snapshot
manifest as an explicit null when absent rather than omitted. The distinction is
the point: a reader can tell an archive that predates stamping from one that
predates the field, and neither defaults into a provenance claim.

The archive reads the manifest entry once, before taking any snapshot, and the
read moved earlier for a reason - the drop that follows a successful data-tier
archive destroys the very entry the record lives in, so the archive is the only
copy a restore could ever be judged against. An unstamped collection archives no
provenance rather than the archiving process's own, which never touched those
vectors.

Nothing reads a snapshot manifest back today; there is no restore verb to wire a
judgement into. Recording the fact is the whole of what this Step can honestly
deliver, and the record is now complete enough for one to be built.

## Notes

The identity read replaced a later duplicate read of the same manifest entry, so
the archive now loads it once instead of twice.
