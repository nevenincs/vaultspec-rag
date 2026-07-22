---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S94'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Retain resolved routing when preprocessing execution is disabled and mark affected work stale without deletion or reclassification

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`
- `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Retain valid preprocessing rules when execution mode is off.
- Suppress worker context without erasing content ownership.
- Exclude disabled transforms from raw execution and surface them as stale work.
- Preserve published IDs, metadata, and cache state across scoped, unscoped, full, and requested clean reconciliation.

## Outcome

The preprocessing kill switch changes execution only. Matching paths keep their declared
owner, are never raw-reclassified, and retain published state until execution resumes or an
explicit membership policy changes.

## Notes

Static formatting, lint, type, and deletion-safety review passed. Real behavior verification
is consolidated in S95 at the phase boundary.
