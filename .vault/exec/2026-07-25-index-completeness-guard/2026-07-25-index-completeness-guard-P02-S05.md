---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S05'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Render the shortfall as a CLI warning naming the deficit and the remedy on both the service and local search paths, and confirm the MCP code search tool already carries the field without recomputing it

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Render the shortfall as a warning naming the live and published counts, the
  deficit, what it means for an absent result, and the remedy.
- Call it on both human-mode service branches, with results and without.
- Carry the same block through the local in-process path, filled from the count
  that path already took, so no second count is paid there either.

## Outcome

Landed in `cfbff066`. Both CLI paths warn, and JSON mode carries the figures
verbatim.

The renderer compares nothing. It prints the conclusion the service settled and
returns early when the field is absent, so there is one implementation of the
completeness judgement and the adapters only present it.

The MCP tool needed no change. Its response model declares extra fields
permitted and names the index-state block as a carried diagnostic, so the field
reaches an MCP client already. Confirmed by reading the model rather than
assumed: adding a pass-through there would have been a second copy of a
transport that already works.

## Notes

The local path fills the block through an out-parameter rather than a fresh
count, mirroring how the search path already threads its notes mapping. Reading
the count again would have been the one thing the decision forbids: a second
store round trip on every query.
