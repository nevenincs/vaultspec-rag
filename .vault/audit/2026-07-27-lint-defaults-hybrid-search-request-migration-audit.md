---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:dd607ef8c9ffd627c5be677744b955ff29bec68f5a52eeb60a3b7dce6fad4fa9'
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
