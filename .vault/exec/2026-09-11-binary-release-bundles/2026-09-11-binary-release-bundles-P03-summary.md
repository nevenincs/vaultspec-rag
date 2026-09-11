---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:7d14df4837adaec0c934653b9f5a52a08f5026f80790a68bf191d62e1b07aa11'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# `binary-release-bundles` `P03` summary

## Changes

- `M` `justfile`
- `M` `tools/packaging/generate.py`
- `M` `tools/packaging/homebrew.py`
- `M` `tools/packaging/scoop.py`
- `M` `tools/packaging/validate.py`
- `A` `tools/packaging/tests/test_committed_channels.py`
- `M` `tools/packaging/tests/test_bundles.py`
- `M` `tools/packaging/tests/test_checksums.py`
- `M` `tools/packaging/tests/test_generators.py`
- `M` `tools/packaging/tests/test_validate.py`
- `M` `docs/installation.md`
- `M` `RELEASING.md`
- `verify:` `uv run --no-sync pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
- `verify:` `uv run --no-sync ruff check tools/binaries tools/packaging` -> `pass`
- `verify:` `just check-markdown check-docs-version check-docs-conventions` -> `pass`
- `verify:` `just check-links` -> `pass`
