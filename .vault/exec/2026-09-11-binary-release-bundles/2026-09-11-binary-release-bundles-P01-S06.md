---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:c4abbbb51a92ef70517870fe695fb53c137dae3e61581ef6848a174d4b40ade6'
step_id: 'S06'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Prove Windows icon and version resources, finalization ordering, platform-floor behavior, and checksum timing with fixture and real PE coverage

## Scope

- `tools/binaries/tests`

## Changes

- `M` `tools/binaries/tests/test_windows_icon.py`
- `M` `tools/binaries/tests/test_build_pyapp.py`
- `verify:` `uv run ruff check tools/binaries/tests/test_windows_icon.py tools/binaries/tests/test_build_pyapp.py` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests/test_windows_icon.py tools/binaries/tests/test_build_pyapp.py tools/binaries/tests/test_platform_floor.py -q` -> `pass`
