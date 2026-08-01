---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:2a8a749264c9fb71718d5ca3149db9851261f9cb8e69c253696a4dba0d6351c4'
step_id: 'S04'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_operator_commands.py`

## Description

- Introduce immutable `IndexCommandOptions` for optional index-command flags.
- Migrate all non-default production and guard-test callers.
- Resolve the review-found caller omission and repeat focused verification.

## Outcome

Operator remediation commands retain their exact flag ordering and values through one
cohesive options value; scoped lint, strict typing, CLI, and guard tests pass.

## Notes

The shared route module retained its unrelated in-progress refactor; only the one
operator-command call site belongs to this step.
