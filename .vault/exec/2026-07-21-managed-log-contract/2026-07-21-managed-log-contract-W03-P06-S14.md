---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S14'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Document generic managed-log environment variables and aggregate retention semantics

## Scope

- `docs/configuration.md`

## Description

- Document the generic retention environment variables and defaults.
- Explain that the policy applies independently to service and Qdrant logs.
- State the approximate aggregate default retention budget.

## Outcome

Configuration documentation now matches the clean-break managed-log policy.

## Notes

The default aggregate is approximately 120 MiB across both active files and backups.
