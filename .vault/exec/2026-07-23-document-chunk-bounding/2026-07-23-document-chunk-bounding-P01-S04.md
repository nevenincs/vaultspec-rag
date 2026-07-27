---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-27'
step_id: 'S04'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# carry title, section, anchor, locator, and unit metadata onto every fragment produced from one unit

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Copy `title`, `section`, `anchor`, `locator`, and unit metadata onto every fragment produced from one unit in `_document_chunks_from_output`.
- Hoist the per-unit `DocumentMetadata` conversion out of the fragment loop so all fragments share one converted mapping.

## Outcome

Retrieval provenance is unchanged for units that fit and correctly attributed for units that split; covered by the oversized-unit test asserting every fragment carries the parent's fields.

## Notes

Template evidence: intro_commit=2b44d249d2461916216580e2c02d7162013b3ccd; template_commit=2b44d249d2461916216580e2c02d7162013b3ccd:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
