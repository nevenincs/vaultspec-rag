---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:8d8b844a3ab0de8e421173ebc7d8f974bd2152bac7dc4502ea9fcb1421e1eb27'
step_id: 'S20'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# run the full unit suite and the citation-gate lint over every changed file

## Scope

- `src/vaultspec_rag/tests`

## Description

- Run the full unit suite (integration and benchmarks excluded) and the citation gate over the tree.

## Outcome

2271 passed plus the new tests; citation gate clean; ruff, ruff format, ty, and the complexity gate all green on every changed file.

## Notes

Three failures are pre-existing at HEAD and unrelated: two shutdown-log tests stub `_terminate_pid` without the `console_group_signal` keyword another session's in-flight CLI work added, and one orphan-reap test passes in isolation. None touches this plan's files. Integration suites were not run: they require the resident machine service stopped, which this execution was explicitly forbidden to do.
