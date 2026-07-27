---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
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

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
