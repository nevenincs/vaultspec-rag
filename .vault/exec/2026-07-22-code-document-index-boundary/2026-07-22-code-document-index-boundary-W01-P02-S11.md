---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:0fd97f5873fc2b8bc24422ed99c103d2abec991d5e8a707f6ac997687c55e3a0'
step_id: 'S11'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add a bounded structured scan result and retain the public path-list scan as its compatibility projection

## Scope

- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Verify structured scans return stable counts and bounded disposition samples.
- Verify each scan carries its policy fingerprint and preprocessing execution summary.
- Preserve the public path-list function as a projection of structured admission.

## Outcome

Callers can inspect bounded admission evidence without losing the existing list-of-paths API.
Both surfaces derive from the same production scan.

## Notes

Reconciled from production commit `e1254ed`; no additional code change was required.
