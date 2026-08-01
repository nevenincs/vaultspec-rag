---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:784b7878ec058975d7fcb75bfa0befc56bbb9519fc0a864d666b9c5b8f5f5acd'
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
