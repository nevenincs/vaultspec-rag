---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:3562752d3507f3fc1ed57106b834f4afaca0a5a8a5e0cfba7f4305b2d71b200f'
step_id: 'S15'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Decompose watcher responsibilities and migrate all direct importers

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

Move watcher event classification, durable retry state, and retry-settlement
ownership to their concrete modules. Migrate server and test consumers to
watcher control and those direct owners, then remove the former watcher module.

Correct the watcher graph-cache ADR guard so it proves the immutable
`WatcherConfiguration` contract rather than a removed direct parameter.

## Outcome

No direct importer resolves through `watcher.py`. The watcher control contract
keeps `graph_cache` on `WatcherConfiguration` and no longer exposes the old
private searcher parameter. An independent review found and verified that
contract correction. Fifty focused watcher and ADR-regression tests passed,
and scoped formatting, lint, and type checks passed.

## Notes

The repository-wide structural duplicate guard still reports only unrelated
CLI, index-policy, and search groups. This step used explicit watcher paths
and did not alter unrelated archive-plan whitespace.
