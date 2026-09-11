---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:8010a4d214c4b9ab8502108d4230aa17b985f93e22146d624ed2f6e033517bfb'
step_id: 'S07'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Accept a version-checked release wheel as the PyApp input while preserving RAG's pinned CUDA torch bootstrap channel

## Scope

- `tools/binaries/build_pyapp.py`

## Changes

- `M` `tools/binaries/build_pyapp.py`
- `M` `tools/binaries/tests/test_build_pyapp.py`
- `verify:` `uv run ruff check tools/binaries/build_pyapp.py tools/binaries/tests/test_build_pyapp.py` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests/test_build_pyapp.py -q` -> `pass`
