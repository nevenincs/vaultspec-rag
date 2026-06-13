---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S20'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add per-dependency skip flags for torch, models, and qdrant to the install command for finer opt-out than --local-only

## Scope

- `src/vaultspec_rag/cli/_install.py`

## Description

- Add `--skip-torch`, `--skip-models`, and `--skip-qdrant` Typer options to the
  `install` command for finer opt-out than the headline `--local-only`.
- Map the three boolean flags onto the front door's `skip` token set
  (`{"torch", "models", "qdrant"}`) at the CLI edge and pass it as `provision_skip` to
  `install_run`.

## Outcome

- Each `--skip-*` flag opts its named dependency out of provisioning, reported as
  `skipped` with an opted-out reason in the outcome.
- Persona check: `install --help` renders all three skip flags with their help text.
- Flag→skip-set mapping is covered by `test_skip_models_flag_maps_to_skip_token` and
  `test_skip_qdrant_flag_maps_to_skip_token` through the real `CliRunner`. `ruff` and
  `ty` clean.

## Notes

`--skip-torch` is honest about a no-op at the CLI level: the enrollment torch step runs
regardless and the front door already skips torch internally (S18), so `--skip-torch`
maps the token through for symmetry and future-proofing rather than altering the current
enrollment torch behaviour. No issues.
