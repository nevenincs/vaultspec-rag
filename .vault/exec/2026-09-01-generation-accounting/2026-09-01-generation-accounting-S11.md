---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:7940b448b463d41c0f0aaf1a27b4a6a17814403384c6b14f4f92c42a72a94dd5'
step_id: 'S11'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Constrain clean-generation reconciliation to the active build collection before publication

## Scope

- `src/vaultspec_rag/indexer/_route_migration.py`

## Description

- Scoped code route scans and same-kind deletion to the lifecycle-derived build collection.
- Purged the private clean-generation target before writing its breadth claim.
- Deferred code-destination replay and cross-kind cleanup until the replacement is published and bound, while excluding any same-kind mutation after the count is recorded.
- Kept document reconciliation and in-place code reconciliation on their existing destination selection.

## Changes

- Extended the canonical code-content scan to select an explicit collection and retained one target-scoped route-scan configuration.
- Split clean-generation same-kind purge from post-publication cross-kind convergence without adding a parallel publication path.

## Outcome

Clean publication now keeps the served code collection and document origins intact until a target-scoped build has been purged, counted, published, and selected. Post-publication route cleanup cannot alter the certified code breadth.

## Notes

Focused formatting, lint, `ty`, and strict `basedpyright` checks passed. The relevant integration selection correctly refused before collection because no compatible resident machine-pointer service was captured; `test_run_checkpoint.py` completed with 28 passing unit tests.
