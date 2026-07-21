---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
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
