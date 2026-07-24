---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S03'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Render a determinate Rich bar in the start wait when total is present, falling back to the named spinner for a descriptor-less daemon

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Added `_startup_count_suffix`, and had `_startup_phase_label` append a space-prefixed `(done/total)` suffix when the published status carries `phase_total`.

## Outcome

The wait spinner renders `loading models (2/3)` when the daemon publishes a count, and the plain stage label when it does not - so a countless stage or an older daemon degrades cleanly.

## Notes

The descriptor-less fallback is guard-tested in `S05`.
