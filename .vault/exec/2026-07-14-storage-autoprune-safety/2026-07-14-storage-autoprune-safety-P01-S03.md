---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:80a6ffdf557da4571ddf5bfb53005f833f87d9592f28d803adb24e9cab6e5556'
step_id: 'S03'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Add the storage_autoprune knobs (enabled, interval_minutes, grace_hours, grace_hours_data, archive_retention_days, max_per_cycle) following the existing env and config-file naming

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add seven `storage_autoprune*` knobs across the three config surfaces
  (`EnvVar` members, `_ENV_OVERRIDE_MAP`, `_RAG_DEFAULTS`): enabled (default
  on), interval 60 minutes, grace 24h (empty tier) and 168h (data tier),
  archive retention 30 days, archive cap 20GB, and max 16 reclaims per
  cycle. Type coercion (bool/int/float) rides the existing default-driven
  env parsing.

## Outcome

Knobs resolve through env and config file like every other setting; all 45
config unit tests pass; ruff, ruff format, and basedpyright clean.

## Notes

`storage_autoprune_archive_max_gb` is the one knob beyond the ADR's list,
implementing its "archive dir capped by total bytes" bound explicitly.
