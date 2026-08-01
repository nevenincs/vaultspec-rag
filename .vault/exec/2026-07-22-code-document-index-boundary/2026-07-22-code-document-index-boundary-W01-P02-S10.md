---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c644d2c6090ff7d232a378b42a3192064925e924bac7a4e75115af9d5aceeb80'
step_id: 'S10'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Route scoped discovery through the shared classifier and resolved policy snapshot

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Verify scoped paths normalize to project-relative policy identities.
- Verify scoped admission delegates to the supplied immutable snapshot.
- Verify only admitted code-owned paths enter hashing and publication.

## Outcome

Scoped indexing consumes the same ownership and admission authority as full discovery, with
rejections kept out of the code execution path.

## Notes

Reconciled from production commit `e1254ed`; no additional code change was required.
