---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8bb8cd675b2b24083a1197bbbe86b43672f25ec6588093527a2f1207046b05e8'
step_id: 'S37'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Audit ADR conformance, truthful acknowledgement, bounded views, GPU ownership, storage safety, shutdown ordering, MCP scope, and test integrity and apply required corrections using vaultspec-code-reviewer

## Scope

- `src/vaultspec_rag/`

## Description

- Audit the implementation against the service job-control ADR and governing rules.
- Remove admission-time code discovery from reusable job bindings.
- Resolve fresh code execution authority at every runnable attempt.
- Keep restored paused code jobs inert during startup rebinding.
- Preserve exact initial watcher batches and refresh later watcher attempts.
- Add a real paused-job corpus mutation regression.
- Re-run independent architecture and safety review.

## Outcome

The final architecture and safety review passed with no open findings. Normal
code attempts now discover current content when they actually run, restored
paused code jobs bind without scanning, and resumed watcher attempts validate
their current scoped or unscoped work. The focused regression passed and proves
that a file added after paused admission is indexed while a file removed before
resume is excluded. Ruff and Ty pass for the changed implementation and test.

## Notes

The first review found one high-severity stale-discovery defect and one
medium-severity eager-restore defect. Both were corrected before the final
review. No broad test suite was run for this correction; verification used one
real production-behavior regression plus targeted static checks.
