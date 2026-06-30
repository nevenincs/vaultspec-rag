---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S40'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add illustrative licence-clean extractor plugin sketches with the pypdf-BSD versus PyMuPDF-AGPL note (D13)

## Scope

- `docs/preprocessing-hooks.md`

## Description

Added an "Illustrative extractors" section to `docs/preprocessing-hooks.md` with
project-side sketches (PDF via pypdf, XLSX via openpyxl, DOCX via python-docx, XML/XSD via
stdlib xml.etree), each with explicit licence flags, and a callout that PyMuPDF is AGPL-3.0
and must not be the default for a licence-clean project (D13).

## Outcome

Schema-generalisation across formats is documented; the licence-clean stack (pypdf +
openpyxl + python-docx + xml.etree) is named.

## Notes

Extractors are examples for the consumer's `tools/`, never dependencies of vaultspec-rag.
