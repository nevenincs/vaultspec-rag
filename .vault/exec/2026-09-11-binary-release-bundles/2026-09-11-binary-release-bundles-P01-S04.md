---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:33ae0b961a0e6d73ac6e43424afa9a20ff935d90e642a0da4ead97a661e21ded'
step_id: 'S04'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Order binary finalization and bundle inputs so icon, version metadata, permissions, platform-floor checks, and all digests complete before release archives are emitted

## Scope

- `tools/binaries/build_pyapp.py`

## Changes

- `M` `tools/binaries/build_pyapp.py`
- `verify:` `uv run ruff check tools/binaries/build_pyapp.py` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests/test_build_pyapp.py tools/binaries/tests/test_platform_floor.py -q` -> `pass`
