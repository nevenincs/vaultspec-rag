---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:d4f7ce728b13b6ebc9c5bb27c60c9bdc0dee219833661deb1f13afcdb30150f3'
step_id: 'S07'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Add the restore operation that derives the destination prefix from a named root through the existing root hash and recovers each recorded collection into it, reporting through the storage sync vocabulary

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Add the operation that recovers a read archive into a destination namespace named by a root, re-keying each archived collection onto the destination prefix and reporting through the vocabulary the other storage operations already use.

## Outcome

Delivered as `restore_archive` in `src/vaultspec_rag/storage_restore.py`. The destination prefix is derived from the named root through the existing `root_collection_prefix`, the same derivation registration uses, so a restore keys the namespace exactly as an index of that root would.

Each archived collection name is re-keyed onto the destination prefix rather than carried across verbatim, and recovered through the server's uploaded-snapshot recovery with `wait=True`.

The outcome reports through the storage sync vocabulary as `restored`, `would_restore`, or `refused` with a reason.

A collection is registered in the restored list *before* its recovery call returns, because recovery can create the collection before its response crosses the transport boundary; the failure path then deletes what it registered, so a partial restore cannot survive under the already-empty destination the preflight guaranteed.

## Notes

The recovery loop registers a collection in its cleanup list before the recovery call returns rather than after. Recovery can create the collection before its response crosses the transport boundary, so a failure mid-call would otherwise leave a collection nothing knows to remove - under a destination the preflight had certified empty.
