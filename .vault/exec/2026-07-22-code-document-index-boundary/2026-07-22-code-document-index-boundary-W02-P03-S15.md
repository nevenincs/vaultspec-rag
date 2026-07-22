---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S15'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define document chunk, locator, metadata, payload, and result models distinct from source chunks

## Scope

- `src/vaultspec_rag/_store_models.py`
- `src/vaultspec_rag/search/_models.py`

## Description

- Define a document-native locator and canonical immutable metadata value.
- Define document payload and chunk types independently from `CodeChunk` and vault models.
- Define a document-specific search result without widening the legacy result contract.

## Outcome

Document content now has an explicit model boundary that preserves native
locators, document and unit metadata, extractor identity, and vector fields.
Canonical metadata and the complete chunk graph survive pickling deterministically.

## Notes

Formatting, lint, type checking, canonical-metadata materialization, and pickle
round-trip probes passed. No storage mutation was introduced in this step.
