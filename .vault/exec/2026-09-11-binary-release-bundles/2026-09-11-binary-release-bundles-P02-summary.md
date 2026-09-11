---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:6d72fa305f33ec505419cde3c3c97bf528a0d6bb265b71c26784a2461eb47f58'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# `binary-release-bundles` `P02` summary

## Changes

- `M` `tools/binaries/build_pyapp.py`
- `M` `tools/binaries/tests/test_build_pyapp.py`
- `M` `justfile`
- `M` `.github/workflows/binaries.yml`
- `A` `tools/binaries/tests/test_release_workflow.py`
- `M` `.github/workflows/publish.yml`
- `M` `.github/workflows/release-please.yml`
- `verify:` `uv run --no-sync pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
- `verify:` `uv run --no-sync ruff check tools/binaries tools/packaging` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/binaries.yml .github/workflows/publish.yml .github/workflows/release-please.yml` -> `pass`
