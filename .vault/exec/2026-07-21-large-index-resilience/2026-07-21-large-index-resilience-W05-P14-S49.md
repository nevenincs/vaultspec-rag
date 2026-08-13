---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:8eeb24cb0ec5f00218bc05a9553aa2d7f71d3b6ea6a63a8644be2022f3b2e9c9'
step_id: 'S49'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Run the complete project test suite without skips or expected failures

## Scope

- `pyproject.toml`

## Description

- Run the complete unit lane against the finished branch.
- Diagnose and clear the one failure blocking it, which pre-dated this work.
- Cap the qdrant client to the minor line of the reviewed server pin and re-lock.

## Outcome

4228 passed, 2 skipped, 0 failed. Lint, format, and type checks clean across the package.

The suite was red before this step for a reason unrelated to the ledger work: a lockfile bump had moved qdrant-client a minor line ahead of the pinned Qdrant server, and a guard exists precisely to catch that. The client was capped to the server's line rather than the server pin raised, because the pin carries reviewed per-platform SHA256 digests for the download-then-execute boundary. Raising it means minting six new digests, and deriving those from the same source as the artifacts would prove nothing - that is an owner's decision, not a side effect of getting a suite green.

The two skips are declared tier gates, not silent omissions.

## Notes

The GPU-marked lanes are not part of this step's selection and were not run: they need exclusive access to the one machine GPU, which is currently held by the operator's resident service.

Two steps closed by earlier sessions, S50 and S51, still lack execution records. Records were not written for them here - authoring an account of work this session did not perform would be fabrication, and the gap is better left visible.
