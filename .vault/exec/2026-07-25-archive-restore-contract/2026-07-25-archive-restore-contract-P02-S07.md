---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:b7f58b803d59a418007e5f856657621ba6d7d4dff79721b934379d74f236b181'
step_id: 'S07'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Add the restore operation that derives the destination prefix from a named root through the existing root hash and recovers each recorded collection into it, reporting through the storage sync vocabulary and ## Scope

- `src/vaultspec_rag/storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the restore operation that derives the destination prefix from a named root through the existing root hash and recovers each recorded collection into it, reporting through the storage sync vocabulary

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered as `restore_archive` in `src/vaultspec_rag/storage_restore.py`. The destination prefix is derived from the named root through the existing `root_collection_prefix`, the same derivation registration uses, so a restore keys the namespace exactly as an index of that root would.

Each archived collection name is re-keyed onto the destination prefix rather than carried across verbatim, and recovered through the server's uploaded-snapshot recovery with `wait=True`.

The outcome reports through the storage sync vocabulary as `restored`, `would_restore`, or `refused` with a reason.

A collection is registered in the restored list *before* its recovery call returns, because recovery can create the collection before its response crosses the transport boundary; the failure path then deletes what it registered, so a partial restore cannot survive under the already-empty destination the preflight guaranteed.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
