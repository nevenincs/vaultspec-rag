---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S22'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Run the targeted subprocess-GPU regression and adjacent service search diagnostics under supervisor observation

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Run the focused subprocess graphics processing unit regression against an immutable export of committed main.
- Exercise a completed baseline index, a second matching rebuild, four raw HTTP probes, the shared service client, and the official Model Context Protocol stdio client.
- Repeat acceptance after the final consumer-envelope commit.

## Outcome

The latest committed main snapshot passed the focused real-daemon regression: one test passed
and six unrelated tests were deselected. The matching empty request returned the structured
unavailable error, stable unrelated searches remained successful, an existing matching result
remained usable, the shared client preserved failure data, and the stdio tool returned an error.

## Notes

Two earlier runs were diagnostic rather than acceptance. Shared uncommitted route work returned
HTTP 500 before search, so committed main was tested from a non-worktree archive without altering
the shared tree. The first archive then exposed that the nonempty probe lacked a baseline index;
the test was corrected to finish a real clean index before starting the measured rebuild. The
corrected snapshot passed twice, including after the last consumer-contract commit.
