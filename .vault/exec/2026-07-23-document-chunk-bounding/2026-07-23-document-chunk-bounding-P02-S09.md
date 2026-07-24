---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S09'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add a guard test driving a multi-page locator-bearing unit through the splitter and asserting every fragment id is distinct

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`

## Description

- Add a guard test driving a locator-bearing unit through the splitter into 4 fragments and asserting the id set has no duplicates.

## Outcome

Test added as `test_locator_bearing_fragments_have_unique_ids`; a comment names the exact mutation the assertion catches (dropping the fragment ordinal from the locator identity branch).

## Notes

Deviation from the plan's scoped file: the test lives in the new focused module `src/vaultspec_rag/tests/test_document_unit_bounding.py` rather than `test_chunk_worker_parity.py`, whose subject is process-pool parity with heavy fixtures. Failure proof recorded under S16.
