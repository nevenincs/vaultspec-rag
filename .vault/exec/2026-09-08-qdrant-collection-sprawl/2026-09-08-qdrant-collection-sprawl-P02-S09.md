---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:0c5f23f596d6ab8ed51b44c16fcd23e1950d0d709acd12ea18bb31355a3d7326'
step_id: 'S09'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add the ephemeral-orphan grace window as a configuration default alongside the existing autoprune knobs

## Scope

- `src/vaultspec_rag/config/_settings.py`

## Changes

- `M` `src/vaultspec_rag/config/_settings.py`
- `M` `src/vaultspec_rag/config/_schema.py`
- `M` `src/vaultspec_rag/config/_types.py`
- `M` `docs/configuration.md`
- `M` `.env.example`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-markdown` -> `pass`
- `verify:` `just check-links` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_configuration_doc.py src/vaultspec_rag/tests/test_env_example_coverage.py src/vaultspec_rag/tests/test_config.py src/vaultspec_rag/tests/test_index_lifecycle.py` -> `pass`
