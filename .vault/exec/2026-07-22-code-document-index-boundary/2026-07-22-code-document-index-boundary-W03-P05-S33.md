---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S33'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Key extraction cache entries by source path, source hash, output schema, and canonical execution fingerprint

## Scope

- `src/vaultspec_rag/indexer/_preprocess_cache.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Replace command-only cache keys with source path, source hash, output schema, and canonical execution identity.

## Outcome

Options, extractor version, target, mode, emitted-byte cap, and invocation changes
invalidate cache entries deterministically. Cache hits are revalidated against the
active emitted-byte cap before reuse.

## Notes

Successful cache entries remain an optimization and are revalidated on read.
A real extractor/cache integration check proves version, path, and cap changes miss.
