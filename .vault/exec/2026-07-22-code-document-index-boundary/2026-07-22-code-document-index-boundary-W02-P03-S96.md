---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S96'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Include document collections and bounded counts in storage survey output

## Scope

- `src/vaultspec_rag/storage_survey.py`

## Description

- Recognize the declared document collection suffix during namespace grouping.
- Compute independent vault, code, and document point totals from bounded integers.
- Preserve aggregate point and footprint accounting for lifecycle decisions.

## Outcome

Every namespace survey carries an explicit document point count alongside the
existing aggregate, without inferring ownership from repository layout.

## Notes

Formatting, lint, and type checks passed. Real survey counts are verified in S121.
