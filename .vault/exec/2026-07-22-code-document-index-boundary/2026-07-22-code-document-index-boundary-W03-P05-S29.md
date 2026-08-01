---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b93152d03c03b844e426571260c700cdd13c0a463f2dc8550817850dcdb92af5'
step_id: 'S29'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define a versioned extractor invocation envelope with canonical source identity, normalized options, configured version, target, and mode

## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`
- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Define a frozen, versioned invocation envelope with canonical project-relative identities, normalized options, configured extractor version, target, and execution mode.

## Outcome

Command and entry-point extractors now receive one deterministic host-owned envelope.

## Notes

The envelope is delivered through a curated environment variable and can be loaded through the public schema helper.
