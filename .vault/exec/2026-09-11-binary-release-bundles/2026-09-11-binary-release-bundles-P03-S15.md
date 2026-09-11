---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:2f1da85fbd6f5d90d3a8c17c4de188991066b2c1d28eacb12ec6595241096a74'
step_id: 'S15'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Document direct-download archive layout, supported targets, manifest and checksum verification, and GPU/network/CUDA first-launch requirements

## Scope

- `docs/installation.md`

## Changes

- `M` `docs/installation.md`
- `verify:` `uv run mdformat docs/installation.md` -> `pass`
- `verify:` `uv run pymarkdown --config .pymarkdown.json scan docs/installation.md` -> `pass`
- `verify:` `just check-markdown check-docs-version check-docs-conventions` -> `pass`
- `verify:` `just check-links` -> `pass`
- `verify:` `uv run python -c "bundle names and supported targets"` -> `pass`
