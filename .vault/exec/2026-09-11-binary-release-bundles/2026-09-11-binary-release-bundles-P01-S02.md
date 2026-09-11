---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:3104f3c42a75a51093640368b1c4db74ab5182460e1c000be7b2b55216ca309e'
step_id: 'S02'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Implement deterministic per-target ZIP and TAR.GZ bundle creation with stable executables, manifest, license, usage material, and checksum sidecars

## Scope

- `tools/packaging/bundles.py`

## Changes

- `A` `tools/packaging/bundles.py`
- `verify:` `uv run ruff check tools/packaging/bundles.py` -> `pass`
- `verify:` `uv run pytest tools/packaging/tests -q` -> `pass`
