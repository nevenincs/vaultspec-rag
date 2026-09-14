---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:52dd8f7d72a6f2ae2aa6fc4c8a755cf183fe6460c5a1059f099262d0efa9c7aa'
step_id: 'S02'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Implement deterministic per-target ZIP and TAR.GZ bundle creation with stable executables, manifest, license, usage material, and checksum sidecars

## Scope

- `tools/packaging/bundles.py`

## Changes

- `A` `tools/packaging/bundles.py`
- `verify:` `uv run --no-sync ruff format --check tools/packaging/bundles.py` -> `pass`
- `verify:` `uv run --no-sync ruff check tools/packaging/bundles.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright tools/packaging/bundles.py` -> `pass`
- `verify:` `uv run --no-sync pytest tools/packaging/tests/test_bundles.py -q` -> `pass`
- `verify:` `git diff --check -- tools/packaging/bundles.py` -> `pass`
