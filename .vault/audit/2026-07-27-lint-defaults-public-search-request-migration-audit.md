---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# `lint-defaults` audit: `public search request migration`

## Scope

Review the request-value migration for public document and combined search facades.

## Findings

No findings. The immutable request values preserve all facade filters, package lazy
exports, and direct CLI/server callers without retaining a compatibility signature.

## Recommendations

No follow-up is required.
