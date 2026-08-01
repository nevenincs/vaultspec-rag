---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:0a0fe8b4f1882a272d3832d2a6d745ef71ae231a98e3a14edc29bcc3687c9cd6'
step_id: 'S34'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Permit cross-path cache reuse only for extractors that explicitly declare path independence

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`
- `src/vaultspec_rag/indexer/_preprocess_cache.py`

## Description

- Add an explicit path-independent rule capability with a fail-safe false default.

## Outcome

Byte-identical files at different paths do not alias unless the extractor opts into cross-path reuse.

## Notes

Real filesystem cache tests cover both the default isolation and explicit reuse cases.
