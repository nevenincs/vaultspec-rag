---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:21ec4ffa1c6a9b3db95124475be676b1f37f9d246209e723bbb428f5c0c1696e'
step_id: 'S31'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Deliver the invocation envelope to entry-point extractors with the same contract as command execution

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Deliver the identical canonical envelope to the out-of-process entry-point runner.

## Outcome

Entry-point and command forms now share the same execution contract and isolation boundary.

## Notes

Entry-point implementations can load the validated envelope through the schema helper.
