---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add the document collection to storage manifest recording and schema compatibility

## Scope

- `src/vaultspec_rag/storage_manifest.py`
- `src/vaultspec_rag/store_schema.py`

## Description

- Define one canonical ordered collection-name projection in the storage schema.
- Record schema generation and exact vault, code, and document names per namespace.
- Infer legacy two-collection manifests conservatively and upgrade them on record.

## Outcome

The persisted storage manifest now describes document ownership explicitly and
retains that evidence across activity stamps, orphan clocks, and prefix rekeys.

## Notes

Formatting, lint, and type checks passed. Legacy entries remain readable as
schema generation 1 until an idempotent current record upgrades them.
