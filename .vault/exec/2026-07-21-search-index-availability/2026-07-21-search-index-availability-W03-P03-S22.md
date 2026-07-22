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
- Exercise a five-party barrier during a real clean rebuild: raw matching, unrelated-root and
  unrelated-source requests, the shared client, and the official Model Context Protocol client.
- Restart against the same storage with a real persisted paused rebuild and prove a known
  nonempty result remains HTTP 200 without lifecycle mutation.

## Outcome

The immutable `fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3` snapshot passed the focused
real-daemon regression: one test passed and seven were deselected in 59.90 seconds. Matching
empty search returned the structured unavailable error, unrelated controls remained successful,
the shared client and stdio tool preserved failure semantics, post-convergence empty search
returned HTTP 200, and the separate persisted-paused phase preserved a known nonempty result.

## Notes

Earlier runs were diagnostic rather than acceptance. One preserved run exposed the actual
collection-disappearance race: after Qdrant dropped the selected collection, a structured
collection-missing 404 escaped as HTTP 500. Commit `fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3`
converted only that evidenced race to the canonical 503. The green lifecycle is not timed to
force the 404 branch; the real red trace and focused real-object tests provide that proof.
