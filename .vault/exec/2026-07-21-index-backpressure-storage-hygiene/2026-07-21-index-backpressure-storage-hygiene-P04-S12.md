---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:4a0fa9c810190771963740ec34bf75b8f5e07759f4a238afd0eed57f7ff66499'
step_id: 'S12'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# canonicalize Windows device-prefix aliases before hashing in root_collection_prefix so an extended-length alias cannot mint a duplicate namespace

## Description

### Scope

- `src/vaultspec_rag/_store_models.py`

Verified upstream PR 245's normalization: `root_collection_prefix` strips
the extended-length device prefixes (plain and UNC forms) before
resolve+normcase, and it is the single hashing authority (store
namespacing, `record_root`, `remove_root`, `rekey_prefix`, root-addressed
delete all call it), so one fix covers registration, teardown, and rekey.
The alias regression test ships upstream; no gaps found.

## Outcome

Closed as verified-upstream; no code authored on this branch.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
