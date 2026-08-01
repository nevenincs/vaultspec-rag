---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:83efb603d34d47fd57dfb33d01ff461bcf0a9e31e964f59f677f3fd4784e91ef'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W04.P08` summary

Completed bounded destination-first route migration, interruption replay, missing-sidecar
recovery, and prior-owner watcher scheduling.

- Commit: `8e6c2114 feat(index): reconcile content routes safely`
- Added: `_route_migration.py`, `test_content_route_migration.py`,
  `test_document_watcher.py`
- Modified: `_codebase_indexer.py`, `_document_indexer.py`, `store.py`, `watcher.py`

## Description

Stored rows are surveyed in bounded pages and freshly classified by the active policy.
Each route flip requires destination file-completion evidence before a durable migration
journal authorizes origin deletion. Cleanup identities are journaled in batches of at
most 256 and replay idempotently from interruption before deletion or after deletion.
Generation-ledger evidence retains confirmed points when metadata is missing and removes
uncertified same-kind debris without deleting an opposite-kind destination candidate.

Deleted watcher paths use their prior ledger owner, while policy control events schedule
code and document convergence independently. The CPU boundary passed 17 focused ledger,
watcher, migration, and storage tests. The model-backed boundary passed a real
code-to-document-to-code ownership flip in 59.11 seconds, with each destination upsert
preceding origin deletion and exact final collection counts.
