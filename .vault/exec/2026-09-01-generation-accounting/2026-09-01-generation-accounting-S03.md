---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:b6df2297b211fee953be0f25b89442c1c6618fc7b9781a295be0b8647b05d1c2'
step_id: 'S03'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Resolve the reindex timeout at the production HTTP call boundary

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Changes

- Resolve the reindex request timeout through the transport's shared runtime settings resolver.
- Retain the reindex-specific shipped default when the configured value is unusable.

## Outcome

The reindex HTTP request now observes the current supported timeout setting at
the production call boundary without adding a parallel configuration path.

## Notes

Focused format, lint, strict type, and existing reindex transport coverage passed.
