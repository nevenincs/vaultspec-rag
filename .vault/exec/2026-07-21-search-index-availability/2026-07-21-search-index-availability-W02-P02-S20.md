---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:3a53a6f70c7dff8560cf4110d333001ecb72fcddbcc19fe72c3a9670a0093454'
step_id: 'S20'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Integrate double job-state observation and HTTP 503 emission into the search route using Terra xhigh

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Capture a copied job snapshot after root validation and before search admission.
- Reobserve job state only for an otherwise-successful empty search.
- Emit HTTP 503 when either observation contains matching nonterminal work.
- Preserve HTTP 200 for stable empty and nonempty searches.
- Preserve search metrics, watcher scheduling, and bounded completion logging.

## Outcome

Integrated the double-observation contract into `search_route`. Focused Ruff formatting and
lint checks passed, basedpyright reported no errors, and independent review approved the
route behavior and campaign isolation.

## Notes

The shared merge completed during execution, so the route was reread and the narrow change was
reapplied to the merged source. Incoming service-job-control changes were preserved.
