---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:41e39bd29d177ab79262414769323e44dab4ed8b67d6706a29d9e0d7f5fadaf7'
step_id: 'S09'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Route full and unscoped discovery through the shared classifier and resolved policy snapshot

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Verify full discovery receives an immutable resolved policy.
- Verify unscoped incremental discovery delegates to the same structured classifier.
- Verify membership and content epochs derive from that exact snapshot.

## Outcome

Full and unscoped code discovery now share one classifier and one operation-scoped policy;
neither path reloads routing while enumerating the repository.

## Notes

Reconciled from production commit `e1254ed`; no additional code change was required.
