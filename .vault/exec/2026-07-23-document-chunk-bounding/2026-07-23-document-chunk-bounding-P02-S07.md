---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-27'
step_id: 'S07'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# bump the document identity version because the derivation changes for units that split

## Scope

- `src/vaultspec_rag/indexer/_document_identity.py`

## Description

- Bump `DOCUMENT_ID_VERSION` from 1 to 2 with a comment stating the derivation change and the deliberate full re-key of previously indexed document corpora.

## Outcome

The identity derivation change is versioned; the first run after this lands re-indexes hook-backed corpora in full, an expected one-time cost rather than a diagnosable regression.

## Notes
Template evidence: intro_commit=2b44d249d2461916216580e2c02d7162013b3ccd; template_commit=2b44d249d2461916216580e2c02d7162013b3ccd:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
