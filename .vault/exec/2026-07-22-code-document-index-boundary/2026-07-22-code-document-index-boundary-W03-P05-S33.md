---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a910c2303c7a14b6251961c5932d45f38a18ca9f0ed59cd1b438245c49085be4'
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
