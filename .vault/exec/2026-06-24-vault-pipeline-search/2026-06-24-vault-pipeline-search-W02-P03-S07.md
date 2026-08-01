---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-07-27'
body_hash: 'sha256:ef01aa67579aefe31bd2d88c5f8ab1801cd01a67c157cc08de58902f5eab349d'
step_id: 'S07'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Parse status from the ADR H1 and strip the status suffix from the displayed title

## Description

### Scope

- `src/vaultspec_rag/indexer/_vault_prep.py`

- Added backtick/whitespace-tolerant `_STATUS_RE` and `_STATUS_SUFFIX_RE` patterns for the
  canonical ADR H1 status marker.

- Refactored title extraction into `_first_h1` (raw heading) plus `_extract_title`, which now
  strips the trailing `| (**status:** ...)` suffix - fixing the prior leak of the marker into
  the displayed title.

- Added `_extract_status` returning the lowercased status value, or empty for legacy
  no-marker and non-ADR headings (callers treat empty as unknown/active).

- Exported the new helper in `__all__`.

## Outcome

Extraction verified across all four heading forms: modern accepted/proposed yield the value
and a clean title; the legacy `# ADR: ...` heading and a plain plan heading yield empty
status with the title unchanged. `ruff` and `ty` pass. Wiring of the value onto
`VaultDocument` is deferred to S08 so this step leaves the module in a working state.

## Notes

`_extract_status` is defined and exported but not yet consumed here; S08 wires it into
`prepare_document` once `VaultDocument` carries the field. No blockers.
