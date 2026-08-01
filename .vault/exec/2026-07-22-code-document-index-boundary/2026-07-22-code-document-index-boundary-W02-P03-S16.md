---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:4f33ab96d3ee4540f7072cf41cdc3be45d763b179f8634a961a5d7d818047d69'
step_id: 'S16'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Implement collection-local document point identities from normalized source, native locator or unit ordinal, and content fingerprint

## Scope

- `src/vaultspec_rag/indexer/_document_identity.py`

## Description

- Normalize caller-provided source paths to safe project-relative POSIX identities.
- Prefer a native locator when present and fall back to unit ordinal deterministically.
- Hash normalized source, location, and content fingerprint into a versioned document ID.

## Outcome

Document points now have deterministic collection-local IDs that remain stable
across path separator spellings and unit reordering when a native locator exists.
The source-code point identity implementation was not changed.

## Notes

Formatting, lint, type checks, separator normalization, locator stability, and
content/location distinction probes passed.
