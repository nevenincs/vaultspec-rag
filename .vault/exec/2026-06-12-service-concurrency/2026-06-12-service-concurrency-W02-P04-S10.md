---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S10'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Prepend contextual headers (path, class, function) to code-chunk embed text while storing raw chunk content

## Scope

- `src/vaultspec_rag/indexer`

## Description

- Prepend a locational header (path :: class :: function) to code-chunk
  embed text while storing raw chunk content unchanged.
- Stamp an embed-input format marker into the codebase metadata sidecar and
  trigger a one-time clean rebuild when it mismatches or is missing over a
  non-empty collection, so old and new embedding regimes never mix.

## Outcome

Queries can now match code chunks through location and naming context. The
rebuild guard is verified by a GPU integration test.

## Notes

Embed-format marker added beyond the planned scope to prevent silent
mixed-regime degradation on existing installs.
