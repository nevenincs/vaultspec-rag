---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:db236556a6ebe81e619e02ae71904fa4511769b4e991f82c88ec734e7b83d5ba'
step_id: 'S11'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Merge Python wheel and source artifacts with binary bundle digests and assets without clobbering concurrent release checksums

## Scope

- `.github/workflows/publish.yml`

## Changes

- `M` `.github/workflows/binaries.yml`
- `M` `.github/workflows/publish.yml`
- `A` `tools/binaries/tests/test_release_workflow.py`
- `verify:` `uv run pytest tools/binaries/tests/test_release_workflow.py -q` -> `pass`
- `verify:` `uv run pytest tools/binaries/tests tools/packaging/tests -q` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/binaries.yml .github/workflows/publish.yml` -> `pass`
- `verify:` `python -c "from pathlib import Path; import yaml; [yaml.safe_load(Path(path).read_text(encoding='utf-8')) for path in ('.github/workflows/binaries.yml', '.github/workflows/publish.yml')]"` -> `pass`
- `verify:` `uv run ruff check tools/binaries/tests/test_release_workflow.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
