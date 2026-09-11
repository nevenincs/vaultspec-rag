---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:e43744020c861f9f37f4c5c0e892618685e5497ecea649c12c1a65a0f23d7681'
step_id: 'S05'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Prove deterministic archive bytes, exact member layout, manifest hashes and metadata, target naming, and refusal of missing or malformed inputs

## Scope

- `tools/packaging/tests`

## Changes

- `A` `tools/packaging/tests/test_bundles.py`
- `verify:` `uv run ruff check tools/packaging/tests/test_bundles.py` -> `pass`
- `verify:` `uv run pytest tools/packaging/tests/test_bundles.py -q` -> `pass`
