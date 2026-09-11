---
tags:
  - '#exec'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:8041c1a745c45fd91e08ec0bbc03df4c5471ce6454bc3331da8248f6835d99cc'
step_id: 'S16'
related:
  - "[[2026-09-11-binary-release-bundles-plan]]"
---

# Document maintainer bundle publication, complete-target gating, checksum reconciliation, and release recovery

## Scope

- `RELEASING.md`

## Changes

- `M` `RELEASING.md`
- `verify:` `uv run --no-sync mdformat --check RELEASING.md` -> `pass`
- `verify:` `uv run --no-sync pymarkdown --config .pymarkdown.json scan RELEASING.md` -> `pass`
- `verify:` `just check-markdown check-docs-version check-docs-conventions` -> `pass`
- `verify:` `just check-links` -> `pass`
- `verify:` `uv run --no-sync lychee --config lychee.toml RELEASING.md` -> `pass`
- `verify:` `release runbook product/workflow contract check` -> `pass`
