---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:99ad34e4059889a3f4b5e75c5b77cb07713fdd3118611658399b5c7254622911'
step_id: 'S45'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Share the index limiter, writer authority, GPU consumer, and memory policy while isolating per-kind operational state

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Run code and document jobs through the shared manager, project lease, writer authority, GPU gate, and profile policy.
- Keep document index, metadata, retry, circuit, generation, and collection state independent.

## Outcome

Both domains share scarce execution authority without conflating their operational or durable state.

## Notes

The production registry constructs both indexers with the same GPU lock.
