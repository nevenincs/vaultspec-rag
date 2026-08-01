---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:4bd0e52f16ee04042a172fe44bd30650c0e9f0d136cfdd836eeed7f8d0caa924'
step_id: 'S13'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# commit the throughput work with a why-focused message and push to origin main

## Scope

- `git`

## Description

- Record written after the fact; the landing happened across the commits
  below rather than as one closing commit, which is why the Step was checked
  without a record at the time.
- Land the admission gate and the ingest wait policy through merge
  `33aae8e7`, carrying the store-side barrier commit `11a6ee57`.
- Land the vault and document slice-writer overlap through merge `eadef36b`,
  carrying `25f73a6e` (vault split pool plus writer queue) and `87890030`
  (document writer adoption).
- Land the per-job GPU-lock-wait telemetry and the conservative flush
  cadences as `c89b7b50`.

## Outcome

Landed and pushed. Every commit named above is contained in `origin/main`
(verified by ref containment, not by a push log). Each carries a why-focused
message; the barrier commit states the silent-drop failure class it exists
to catch, and the overlap commit records its guard-test mutation proofs
inline.

## Notes

- This Step closed the code landing only. The plan's measurement Steps
  (P02.S05, P03.S09, P04.S11) and the gate Step (P04.S12) were still open at
  the time of the push, so the campaign was landed unmeasured by design of
  the plan's sequencing - the decision record's consequences section says so
  explicitly.
