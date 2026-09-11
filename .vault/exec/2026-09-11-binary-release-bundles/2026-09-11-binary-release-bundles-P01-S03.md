---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:52c8e08700aae8c81770bf89e1b8d4aab608c56a43c8856948977a63fbf2a327'
step_id: 'S03'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Add Windows PE version-resource stamping and read-back verification while retaining icon resource verification

## Scope

- `tools/binaries/windows_icon.py`

## Changes

- `M` `tools/binaries/windows_icon.py`
- `verify:` `uv run ruff check tools/binaries/windows_icon.py` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests/test_windows_icon.py -q` -> `pass`
