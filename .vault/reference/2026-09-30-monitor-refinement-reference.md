---
tags:
  - '#reference'
  - '#monitor-refinement'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:a48d70b7a02e53fa865bea26271a5e9d534c9e5147624f1637a01c21cd7db9b8'
related: []
---

# `monitor-refinement` reference: `Current monitor gaps and reusable service evidence`

## Summary

Source: monitor worktree at c4407c2d, inspected 2026-09-30. Semantic discovery returned index_unverifiable for code and vault; discovery used the owning all-ADR listing and targeted code reads without index recovery.

The terminal owner already provides indexing and serving lanes, revisioned controls, responsive composition and grouped raw logs: `src/vaultspec_rag/cli/_jobs_tui.py:179`.

The header labels indexing-job degradation as service condition while a separate status bar reads daemon health. These scopes differ: `src/vaultspec_rag/cli/_jobs_tui_header.py:239`, `src/vaultspec_rag/cli/_jobs_tui_status.py:277`.

The service returns queued requests and all_counts, but the TUI originally consumed only active/recent: `src/vaultspec_rag/server/_search_activity.py:409`, `src/vaultspec_rag/cli/_jobs_tui.py:681`, `src/vaultspec_rag/cli/_jobs_tui_payload.py:78`.

The selected job log originally fetched only on selection changes. get_logs accepts job_id and contains filters; request-correlated inspection must use the existing contains filter with the request identity, not a nonexistent request_id parameter: `src/vaultspec_rag/cli/_jobs_tui_logs.py:52`, `src/vaultspec_rag/server/_routes.py:883`, `src/vaultspec_rag/serviceclient/_transport.py:1163`.

TypeSafe enrollment publishes redacted state, model, last-success age and retry delay through health. Query/candidate diagnostics provide requests, cache hits, coalescing, token counts, failures and timings: `src/vaultspec_rag/search/_typesafe_transport.py:126`, `src/vaultspec_rag/search/_typesafe_policy.py:80`, `src/vaultspec_rag/server/_routes_search.py:391`.

The original generic timing renderer treated all numeric diagnostics as seconds, including TypeSafe millisecond values and counters: `src/vaultspec_rag/cli/_jobs_tui_cells.py:516`. Preserve actual units.

## Context

# `monitor-refinement` reference: current monitor gaps and reusable service evidence

## Summary

Source: monitor worktree at `c4407c2d`, inspected 2026-09-30. Semantic discovery returned index_unverifiable for code and vault; discovery used the owning all-ADR listing and targeted code reads without index recovery.

The concrete terminal owner already provides indexing and serving lanes, revisioned job controls, responsive composition and grouped raw service/Qdrant logs. Improve that owner rather than adding another monitor: `src/vaultspec_rag/cli/_jobs_tui.py:179`.

The header derives an alleged service condition from indexing-job degradation and reachability of the jobs read, even though a separate status bar reads the daemon health verdict. These are different scopes: `src/vaultspec_rag/cli/_jobs_tui_header.py:239`, `src/vaultspec_rag/cli/_jobs_tui_status.py:277`.

The service already returns queued requests and all_counts in addition to active and recent requests. The TUI validates and paints only active/recent, silently dropping queued requests: `src/vaultspec_rag/server/_search_activity.py:409`, `src/vaultspec_rag/cli/_jobs_tui.py:742`, `src/vaultspec_rag/cli/_jobs_tui_payload.py:93`.

The selected indexing log is fetched only when the selected id changes. Managed logs poll independently, but that does not update the selected log. The existing get_logs transport supports job_id and request_id filters; use those filters to attribute the focused inspection correctly: `src/vaultspec_rag/cli/_jobs_tui.py:1218`, `src/vaultspec_rag/cli/_jobs_tui_logs.py:52`, `src/vaultspec_rag/server/_routes.py:883`.

TypeSafe daemon enrollment already publishes redacted state, model, last-success age and retry delay through health. Query and candidate diagnostics publish requests, cache hits, coalescing, token counts, failures and timings. No provider probing or new credentials are needed for the monitor: `src/vaultspec_rag/search/_typesafe_transport.py:126`, `src/vaultspec_rag/search/_typesafe_policy.py:80`, `src/vaultspec_rag/server/_routes_search.py:391`.

The current generic search-timing renderer treats every numeric diagnostic as seconds, including TypeSafe millisecond timings, token counts and probabilities. Render units explicitly instead: `src/vaultspec_rag/cli/_jobs_tui_cells.py:516`.

## Mapping

Keep health service-owned, indexing condition explicitly scoped to indexing, counters labeled with their retention/page scope, and logs bounded through the existing transport. Reuse stable ids, issue-ordered snapshots and control capability checks. Render daemon TypeSafe evidence without deriving enrollment from the monitor process. Existing accepted jobs, server-watch, managed-log and optional-hosted-classification decisions cover these refinements; no new transport, retention boundary or persisted schema is required.
