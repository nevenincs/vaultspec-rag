---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:13a46b1eee3d5e2ecd535382378bedbb7d80bb27cf9b01e6775a0af2b190b5d5'
step_id: 'S09'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Write the destination manifest entry from the archived per-collection identity and archived schema generation rather than current values, leaving an identity-less archive unverifiable

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

Write the restored namespace's manifest entry from the archive's own records - the archived per-collection identity and the archived schema generation - rather than from what this process is currently configured with.

## Outcome

Delivered as `record_restored_archive` in `src/vaultspec_rag/storage_manifest.py`. The destination entry is written from the archived schema generation and the archived per-collection identities, never from current process values.

An identity-less archive - which is every archive written so far - leaves the identity mapping empty rather than having one invented, so the existing survey path continues to report the namespace `unverifiable`. That is the honest answer: a restore creates no vectors and therefore knows nothing about what produced them.

Guarded by `TestRestoreCarriesArchivedProvenance` in `src/vaultspec_rag/tests/test_storage_restore.py`, both directions proved.

## Notes

The identity field this reads is authored under the storage-conformance plan and remains open there. Nothing here depends on it being populated: every archive written so far carries no identity, and the required behaviour is that an absent one stays absent and the namespace reports `unverifiable`.
