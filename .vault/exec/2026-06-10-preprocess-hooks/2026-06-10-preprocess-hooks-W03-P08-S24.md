---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S24'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Surface preprocess counts in the CLI index --json output (D11)

## Scope

- `src/vaultspec_rag/cli/_index.py`

## Description

The CLI `index --json` codebase source dict now includes `preprocess_skipped` and
`preprocess_failures`, so machine-readable index output never hides a coverage gap (D11).

## Outcome

`vaultspec-rag index --type code --json` reports skip count + file list under the codebase
source entry.

## Notes

Mirrors the IndexResult fields added in S21.
