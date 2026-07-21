---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S11'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add preflight tests covering refusal, pass-through, and envelope shape

## Scope

- `src/vaultspec_rag/tests/`

## Description

Confirmed PR 246's `test_store_writes.py` already covers refusal
(`floor breach`, impossible estimate with canonical disk-full phrasing),
pass-through (ample headroom), and the remote-storage skip (missing local
volume). The only gap was the CLI surfacing, closed in S10 with two new
tests.

## Outcome

Closed as verified-upstream plus the S10 CLI tests.

## Notes
