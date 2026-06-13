---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S19'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add --local-only to the install command so it skips the qdrant binary and selects the local runtime default

## Scope

- `src/vaultspec_rag/cli/_install.py`

## Description

- Add a `--local-only` Typer option to the `install` command, documented as the
  minimal / CI / air-gapped alternative that uses the on-disk store, skips the Qdrant
  binary download, and persists the local backend so `server start` honours it.
- Add a `--provision/--no-provision` toggle defaulting to provision-on so the
  operator-facing surface carries the server-first opt-out polarity.
- Thread `provision`, `local_only`, and the per-dependency skip set through to
  `install_run`.
- Rewrite the command docstring to describe default provisioning of models and the
  Qdrant binary, the `--local-only` headline opt-out, the finer skip flags, and the
  non-interactive flags.

## Outcome

- `vaultspec-rag install --local-only` skips the binary step (reported `skipped` with
  the local-only reason) and persists the local backend selection.
- Persona check (cli-operability-needs-persona-tests): ran
  `uv run --no-sync vaultspec-rag install --help` and confirmed the human help renders
  `--local-only`, `--provision/--no-provision`, and the docstring guidance correctly
  for an operator.
- CLI flag-mapping tests in `test_install_provision.py` (driven through the real Typer
  `CliRunner` in `--dry-run --json`) pass. `ruff` and `ty` clean.

## Notes

The redundant explicit `--skip-qdrant` and the headline `--local-only` both drop the
qdrant binary; they are unioned at the CLI edge, matching the front door's own
`local_only`-implies-skip behaviour. No issues.
