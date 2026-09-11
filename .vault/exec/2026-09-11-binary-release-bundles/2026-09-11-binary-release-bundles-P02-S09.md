---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:24ad2c99e654036e777d2dc2972561ff90420caaba3008cf553f3eb366a15e04'
step_id: 'S09'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Build the exact release wheel, bundle each matrix target, validate archive contents, and upload only validated public archives and sidecars

## Scope

- `.github/workflows/binaries.yml`

## Changes

- `M` `.github/workflows/binaries.yml`
- `verify:` `python -c "import pathlib, yaml; yaml.safe_load(pathlib.Path('.github/workflows/binaries.yml').read_text(encoding='utf-8'))"` -> `pass`
- `verify:` `actionlint -shellcheck= -pyflakes= -no-color .github/workflows/binaries.yml` -> `pass`
- `verify:` `python workflow bundle handoff structural checks` -> `pass`
