---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:f729ad3cb90537665140350b28ec25f0697313e45c7a815b5d930021bfd3cd70'
step_id: 'S12'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Coordinate explicit release-tag dispatch so Python and binary workflows use the same tag and neither partial workflow advances stable/latest

## Scope

- `.github/workflows/release-please.yml`

## Changes

- `M` `.github/workflows/release-please.yml`
- `M` `tools/binaries/tests/test_release_workflow.py`
- `verify:` `uv run pytest tools/binaries/tests/test_release_workflow.py -q` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/release-please.yml .github/workflows/binaries.yml .github/workflows/publish.yml` -> `pass`
- `verify:` `uv run ruff check tools/binaries/tests/test_release_workflow.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
