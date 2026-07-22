---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S02'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define ordered root routing rules independently from optional preprocessing transforms

## Scope

- `src/vaultspec_rag/config.py`
- `src/vaultspec_rag/indexer/_content_policy.py`

## Description

- Define immutable raw route and root-policy configuration values.
- Preserve unknown target tokens for later structured rejection.
- Define typed routes and root policies using the closed content vocabulary.
- Preserve caller precedence exclusively through tuple order.
- Validate formatting, lint, typing, and real order-preserving construction.
- Audit path-layout neutrality and preprocessing independence.

## Outcome

Caller-authored routes now have separate raw configuration and typed domain contracts. Both
are immutable, maintain declaration order, and contain no preprocessing behavior.

## Notes

No incidents or data loss. Route matching, target compilation, conflict detection, and
configuration migration remain assigned to later Steps.
