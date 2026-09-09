---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:95ca627ad91b612fe618b5f770c0a4abe8d634f05adf91e939af12c14a40de47'
step_id: 'S20'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Document adaptive policy defaults, validation, telemetry, and rebuild-required remediation

## Scope

- `docs`

## Changes

- `A` `docs/automatic-convergence.md`
- `M` `docs/configuration.md`
- `M` `docs/service-mode.md`
- `verify:` `uv run mdformat --check docs/automatic-convergence.md docs/service-mode.md docs/configuration.md` -> `pass`
- `verify:` `uv run pymarkdown --config .pymarkdown.json scan docs/automatic-convergence.md docs/service-mode.md docs/configuration.md` -> `pass`
- `verify:` `lychee --config lychee.toml docs/automatic-convergence.md docs/service-mode.md docs/configuration.md` -> `pass`
