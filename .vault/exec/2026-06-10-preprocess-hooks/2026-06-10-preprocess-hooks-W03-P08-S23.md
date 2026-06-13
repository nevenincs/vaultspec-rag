---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S23'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Surface preprocess counts in the jobs registry and watcher summary strings (D11)

## Scope

- `src/vaultspec_rag/server/jobs.py`

## Description

The watcher's code-reindex jobs summary string now appends a `~{preprocess_skipped}` suffix
when non-zero, so `server service jobs` / the `get_jobs` MCP tool surface skipped-file counts
alongside `+added /updated -removed (ms)` (D11). The plan scoped this to `server/jobs.py`;
the result-summary string is actually built in `watcher.py` (jobs.py stores it verbatim),
so the edit landed there.

## Outcome

A reindex that skips files reports e.g. `+0 /2 -0 (812ms) ~3` in the jobs feed.

## Notes

Scope clause adjusted from `server/jobs.py` to `watcher.py` where the summary is composed.
