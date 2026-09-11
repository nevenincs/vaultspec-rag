---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:e951871f23814e58346be673193e6ffe62663d8969ee05b8c3186b835342f1cb'
step_id: 'S08'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Expose reproducible local commands for exact-wheel binary builds, target bundle creation, archive validation, and release checksum generation

## Scope

- `justfile`

## Changes

- `M` `justfile`
- `M` `tools/binaries/tests/test_build_pyapp.py`
- `verify:` `uv run ruff check tools/binaries/tests/test_build_pyapp.py` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests/test_build_pyapp.py -q` -> `pass`
- `verify:` `just --dry-run release-binaries vaultspec-rag-v0.4.6 x86_64-unknown-linux-gnu` -> `pass`
- `verify:` `just --dry-run release-bundle vaultspec-rag-v0.4.6 x86_64-unknown-linux-gnu` -> `pass`
- `verify:` `just --dry-run release-checksums` -> `pass`
