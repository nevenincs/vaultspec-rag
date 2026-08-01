---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:1ea4b179c4d06c90a42f8f177b51854cb2eb17a23755f33bad2b7e14b057d9a8'
step_id: 'S02'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Publish the maintenance cycle's survey into the snapshot slot and add the one-shot startup warmer (survey-only, read-only)

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Extend `MaintenanceResult` with a `surveys` field so `run_maintenance_cycle` hands back the classified survey it already computed (`src/vaultspec_rag/storage_ops.py`)
- Publish it from `_storage_maintenance_tick_sync` via the extracted `_publish_survey_from_cycle`, dropping prefixes the cycle just reclaimed
- Add `_storage_survey_warm_sync` (read-only gather + publish, server-mode gated) and the crash-proof one-shot `_survey_warmup_task` with a 5s delay that only fills a cold slot

## Outcome

The hourly footprint walk is no longer thrown away, and the snapshot is warm minutes after startup instead of one full interval later. Commit 7ae79ca.

## Notes

The publish block was extracted into `_publish_survey_from_cycle` because inlining it pushed the tick to cyclomatic rank D (gate max C). The warmer never advances grace stamps and never reclaims - lifecycle-inertness intact.
