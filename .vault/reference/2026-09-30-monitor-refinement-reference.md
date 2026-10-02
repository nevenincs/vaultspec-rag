---
tags:
  - '#reference'
  - '#monitor-refinement'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:e53990946d9b9f9d14b9e517dafae41c519af1e5eccefcec24753147467c1e12'
related: []
---

# `monitor-refinement` reference: `Current monitor gaps and reusable service evidence`

## Summary

Source: monitor worktree at c4407c2d, inspected 2026-09-30. Semantic discovery returned index_unverifiable for code and vault; discovery used the owning all-ADR listing and targeted code reads without index recovery.

The terminal owner already provides indexing and serving lanes, revisioned controls, responsive composition and grouped raw logs: `src/vaultspec_rag/cli/_jobs_tui.py:179`.

The header originally labeled indexing-job degradation as service condition while a separate status bar read daemon health. These scopes differ: `src/vaultspec_rag/cli/_jobs_tui_header.py:239`, `src/vaultspec_rag/cli/_jobs_tui_status.py:277`.

The service returns queued requests and all_counts, but the TUI originally consumed only active/recent: `src/vaultspec_rag/server/_search_activity.py:409`, `src/vaultspec_rag/cli/_jobs_tui.py:681`, `src/vaultspec_rag/cli/_jobs_tui_payload.py:78`.

The selected job log originally fetched only on selection changes. get_logs accepts job_id and contains filters; request-correlated inspection uses the existing contains filter with the full request identity: `src/vaultspec_rag/cli/_jobs_tui_logs.py:52`, `src/vaultspec_rag/server/_routes.py:883`, `src/vaultspec_rag/serviceclient/_transport.py:1163`.

TypeSafe enrollment publishes redacted state, model, last-success age and retry delay through health. Query/candidate diagnostics provide requests, cache hits, coalescing, token counts, failures and timings: `src/vaultspec_rag/search/_typesafe_transport.py:126`, `src/vaultspec_rag/search/_typesafe_policy.py:80`, `src/vaultspec_rag/server/_routes_search.py:391`.

The original generic timing renderer treated all numeric diagnostics as seconds, including TypeSafe millisecond values and counters: `src/vaultspec_rag/cli/_jobs_tui_cells.py:516`.

## Context

Production managed-log responses include explicit source identity, matching filters, returned tail and byte-budget truncation. Inspectors must validate that contract and retain separate freshness/error evidence. Production HTTP-route tests can use real ledgers and files without a daemon lifespan or inference.

## Mapping

Keep health service-owned, indexing condition explicitly scoped to indexing, counters labeled with their retention/page scope, and logs bounded through the existing transport. Reuse stable ids, issue-ordered snapshots and control capability checks. Render daemon TypeSafe evidence without deriving enrollment from the monitor process. Existing accepted jobs, server-watch, managed-log and optional-hosted-classification decisions cover these refinements; no new transport, retention boundary or persisted schema is required.
