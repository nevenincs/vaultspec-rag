---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S09'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add a service-domain disk preflight (free bytes vs floor plus source-byte estimate) wired into start_reindex_codebase and start_reindex_vault, refusing with a structured disk_preflight_failed outcome

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

Satisfied by PR 246 (merged to main, adopted via merge): a cheap per-write
free-disk floor check in `_store_writes.ensure_disk_headroom` plus bulk
preflights at the vault and code streaming phases and the pipeline path.
Coverage verified: both indexers' incremental and full paths route through
the guarded phases, and a remote server (no local storage dir) skips the
probe instead of misjudging an invisible volume.

## Outcome

Closed as adopted-upstream; no code authored on this branch.

## Notes

The refused run fails in milliseconds with the canonical "No space left on
device" phrasing so job records hit the existing friendly disk mapping.
