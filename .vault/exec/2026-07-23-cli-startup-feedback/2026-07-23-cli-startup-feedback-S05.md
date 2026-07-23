---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S05'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Add unit tests for the descriptor round-trip and the CLI bar/spinner rendering, including the older-daemon fallback guard

## Scope

- `src/vaultspec_rag/tests/test_machine_discovery.py`

## Description

- Added a publisher test asserting `done`/`total` round-trip and that a countless publish omits both keys.
- Added CLI tests for the `(done/total)` suffix and for the descriptor-less older-daemon fallback.

## Outcome

21 unit tests pass. The older-daemon fallback is a guard test verified in both directions.

## Notes

Guard proof: injecting `phase_total`/`phase_done` into the fallback test's status flipped its assertion red for the right reason (`assert 'loading models (2/3)' == 'loading models'`), and removing them restored green - proving the suffix binds to the presence of the count fields, not always emitted.
