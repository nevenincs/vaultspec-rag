---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:3a52c063555b9320832ef70569924f8e729d105088c9326b5330f5cce3c45e68'
step_id: 'S14'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Update channel, checksum, pointer, target-coverage, and archive-contract tests for bundle assets and failure cases

## Scope

- `tools/packaging/tests`

## Changes

- `A` `tools/packaging/tests/test_committed_channels.py`
- `M` `tools/packaging/tests/test_bundles.py`
- `M` `tools/packaging/tests/test_checksums.py`
- `M` `tools/packaging/tests/test_generators.py`
- `M` `tools/packaging/tests/test_validate.py`
- `verify:` `uv run ruff check tools/binaries tools/packaging` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/binaries.yml` -> `pass`
