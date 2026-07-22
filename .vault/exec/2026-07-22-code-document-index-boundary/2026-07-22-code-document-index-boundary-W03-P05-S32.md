---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S32'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reject emitted source redirection and validate bounded document and unit metadata

## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Bind emitted source identity to the invoked host path and bound document and unit metadata.

## Outcome

Source redirection is rejected and metadata remains a bounded payload component.

## Notes

Real subprocess coverage verifies attempted redirection becomes an explicit failure.
The remediation gate also verifies document metadata, unit metadata, titles, sections,
anchors, and locators survive a real extractor process after bounded schema validation.
