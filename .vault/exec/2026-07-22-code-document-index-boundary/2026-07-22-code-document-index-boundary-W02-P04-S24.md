---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S24'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Preserve title, section, anchor, locator, document metadata, unit metadata, and extractor identity on document chunks

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/_store_models.py`

## Description

- Convert validated extractor output into document-native payloads.
- Preserve unit headings, anchors, locators, metadata, and extractor identity.

## Outcome

Stored document chunks retain every supported document and unit field.

## Notes

No unresolved work.
