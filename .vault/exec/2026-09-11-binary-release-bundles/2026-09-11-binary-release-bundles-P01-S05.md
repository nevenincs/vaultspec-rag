---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:ef67bc9a3385385d84c229e5cf70de1930faf680468c3c6a7b9e306681c49dd4'
step_id: 'S05'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---
# Prove deterministic archive bytes, exact member layout, manifest hashes and metadata, target naming, and refusal of missing or malformed inputs

## Scope

- `tools/packaging/tests`

## Changes

- `A` `tools/packaging/tests/test_bundles.py`
- `verify:` `uv run --no-sync ruff format --check tools/packaging/tests/test_bundles.py` -> `pass`
- `verify:` `uv run --no-sync ruff check tools/packaging/tests/test_bundles.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright tools/packaging/tests/test_bundles.py` -> `pass`
- `verify:` `uv run --no-sync pytest tools/packaging/tests/test_bundles.py -q` -> `pass`
- `verify:` `guard mutation: omit member-mode verification` -> `fail as expected, then pass after restore`
- `verify:` `git diff --check -- tools/packaging/tests/test_bundles.py` -> `pass`
