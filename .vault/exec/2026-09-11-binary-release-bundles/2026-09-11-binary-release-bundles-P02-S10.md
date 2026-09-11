---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:c8f2a23817795710b29177210bdc472da75d99ced6bfb9397f2f9a3b4f668ada'
step_id: 'S10'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Gate release asset publication and stable/latest channel promotion on the complete declared target archive set and reject raw executable publication

## Scope

- `.github/workflows/binaries.yml`

## Changes

- `M` `.github/workflows/binaries.yml`
- `A` `tools/binaries/tests/test_release_workflow.py`
- `verify:` `uv run pytest tools/binaries/tests/test_release_workflow.py -q` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/binaries.yml` -> `pass`
- `verify:` `python -c "from pathlib import Path; import yaml; yaml.safe_load(Path('.github/workflows/binaries.yml').read_text(encoding='utf-8'))"` -> `pass`
- `verify:` `uv run ruff check tools/binaries/tests/test_release_workflow.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
