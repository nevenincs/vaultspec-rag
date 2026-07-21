---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S20'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# document the new job outcomes, preflight, ephemeral TTL, and debris reclaim in the storage and CLI docs

## Scope

- `docs/`

## Description

Docs: `storage-maintenance.md` gains the ephemeral idle-TTL section under
automatic reclamation, the `prune --debris` recipe, and the totals/gauge
rows; `configuration.md` adds the ephemeral TTL knob;
`service-mode.md` documents `error_kind` remediation, the `stalled` flag
across surfaces, and `interrupted` restore semantics.

## Outcome

Committed as the docs commit for this feature.

## Notes
