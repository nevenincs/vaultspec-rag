---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:949bb45bf0bcc7fa8538dfbe45ecec2be23643200c3da1ca22277d0e7e550b51'
step_id: 'S08'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Refuse a destination holding any existing collection, a non-canonical destination prefix, and any local-mode invocation, each naming its own reason

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Refuse the three cases where a restore would have to guess: a destination that already holds collections, a destination root that derives no canonical prefix, and a local-mode invocation. Each returns its own reason and mutates nothing.

## Outcome

All three refusals are delivered in `restore_archive`, each returning its own reason and mutating nothing:

- `local_mode_unsupported` - returned before the archive is read at all, so a local-mode call against a nonexistent archive still refuses rather than raising.
- `invalid_destination_prefix` - the named root does not derive a canonical prefix.
- `destination_exists` - any collection already present under the destination prefix. There is no flag that overrides it.

A fourth refusal the step row did not anticipate is also present: `invalid_archive_collection`, for an archive naming a collection that re-keys onto the bare destination prefix.

One platform refusal is inherited rather than added here: an applied restore on Windows returns `windows_server_archive_restore_unsupported`. On this platform the applied path is therefore unreachable and only the preview and the refusals can be exercised, which is why the round trip in `P03` is the step that has to run elsewhere.

## Notes

The local-mode refusal is returned before the archive is read at all. That ordering is deliberate and is asserted directly: a local-mode call naming a nonexistent archive must refuse rather than raise, because the operator's configured backend is the reason, not the archive.
