---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:dbb8fd9af7b985536a0fbc8cdd40dc3f8aea1600fb0707046fb633d5075ac4c7'
step_id: 'S30'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Deliver the invocation envelope to command extractors without shell-specific argument reconstruction

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Deliver the canonical envelope to every bounded command extractor process.

## Outcome

Command execution now receives options and versioned semantics without shell reconstruction.

## Notes

The existing direct argv source operand remains intact for compatibility.
