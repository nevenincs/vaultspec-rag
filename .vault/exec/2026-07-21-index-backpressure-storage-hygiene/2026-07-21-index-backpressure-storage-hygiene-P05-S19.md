---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:06249b717eec70413b1806522ff0af4f49b3dd58fa86f8169aed37a6679a7758'
step_id: 'S19'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add tests for tuned collection config, debris detection, and the total-bytes rollup

## Scope

- `src/vaultspec_rag/tests/`

## Description

`TestDebrisVisibility`: debris detection with footprints, no-storage-dir
no-op, totals rollup across statuses, dry-run leaves dirs in place,
removal spares live-listed dirs, idempotent empty result.

## Outcome

Committed within the P05 storage commit; 37 storage-ops tests green.

## Notes

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
