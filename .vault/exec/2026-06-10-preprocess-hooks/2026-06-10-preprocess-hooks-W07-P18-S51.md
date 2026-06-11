---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S51'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add a unit test that oversize stdout is bounded and skipped (PREPROCESS-003)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_runner.py`

## Description

Added `test_oversize_stdout_is_bounded_and_skipped`: a real extractor writes ~3 MiB of
non-JSON stdout; the runner skips with an "exceeds" reason rather than buffering it all
(PREPROCESS-003).

## Outcome

Passes; confirms the bounded read caps memory and skips oversize output.

## Notes

Real subprocess; the 3 MiB exceeds the 1 MiB floor cap so the bounded path is exercised.
