---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:923a0ebefa31cb11ab968f2b088875adb23b1fc2dc49bdb0aa774d6084c815ed'
step_id: 'S13'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Generate and validate Scoop and Homebrew channels from one archive URL and digest per target while preserving stable extracted command names and glibc caveats

## Scope

- `tools/packaging`

## Changes

- `M` `justfile`
- `M` `tools/packaging/generate.py`
- `M` `tools/packaging/homebrew.py`
- `M` `tools/packaging/scoop.py`
- `M` `tools/packaging/tests/test_generators.py`
- `M` `tools/packaging/tests/test_validate.py`
- `M` `tools/packaging/validate.py`
- `verify:` `uv run ruff check tools/packaging tools/packaging/tests/test_generators.py tools/packaging/tests/test_validate.py` -> `pass`
- `verify:` `uv run pytest tools/packaging/tests/test_generators.py tools/packaging/tests/test_validate.py -q` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
