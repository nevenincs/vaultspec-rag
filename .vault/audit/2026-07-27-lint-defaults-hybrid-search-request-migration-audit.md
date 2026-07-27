---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# `lint-defaults` audit: `hybrid search request migration`

## Scope

Review the hybrid-search request migration through the store, production searcher,
and real direct store/search callers.

## Findings

No findings. The request value preserves dense, sparse, feedback, domain, and filter
inputs across every direct caller.

## Recommendations

No follow-up is required.
