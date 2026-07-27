---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
step_id: 'S15'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add hygiene tests for alias-proof hashing, ephemeral flagging, and TTL-tier reclamation invariants

## Scope

- `src/vaultspec_rag/tests/`

## Description

`TestEphemeralIdleTier` covers: idle empty reclaim, idle data taking the
archive action, fresh-activity pending, missing-stamp pending, non-temp
live untouched, zero-TTL disable, absent-mapping skip, and orphan
priority under a shared cap of 1. `TestLastIndexedStamping` pins the
manifest stamp overwrite. Suite plus manifest/survey/ADR-regression/
indexer suites: 192 tests green.

## Outcome

Committed as `test(storage): ephemeral idle-TTL tier invariants and activity-clock stamping (#242)`.

## Notes

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
