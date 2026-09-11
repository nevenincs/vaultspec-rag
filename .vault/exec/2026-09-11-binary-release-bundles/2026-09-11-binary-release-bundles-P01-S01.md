---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:394a141614d077a346d8080594ebbd9b8429e13bdee52d0dc0c3ea7ef23bdb5e'
step_id: 'S01'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Centralize RAG's supported targets, stable executable names, private staging names, archive suffixes, and release metadata

## Scope

- `tools/packaging/products.py`

## Changes

- `M` `tools/packaging/products.py`
- `verify:` `uv run pytest tools/packaging/tests/test_generators.py -q` -> `pass`
