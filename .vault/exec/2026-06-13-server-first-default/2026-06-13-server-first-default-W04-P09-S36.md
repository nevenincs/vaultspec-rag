---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S36'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# rewrite the installation doc to describe default provisioning of torch, models, and the qdrant binary plus the --local-only opt-out

## Scope

- `docs/installation.md`

## Description

- Added a "pure-Python wheel" note to the install section: the wheel never bundles the Qdrant binary; the binary is fetched at runtime, digest-verified before extraction and execution, over an HTTPS host-pinned download.
- Rewrote the "Run the install command" section to describe the default provisioning of torch, models, and the qdrant binary the server-first default needs.
- Documented the shared sync vocabulary (`created`/`updated`/`unchanged`/`skipped`/`failed`), idempotency, and the `--dry-run` preview.
- Documented torch as a two-phase step ("configured, sync pending" then `uv sync`, with `--sync` as the in-line option).
- Listed every opt-out: `--local-only`, `--skip-torch`, `--skip-models`, `--skip-qdrant`, `--no-provision`, `--no-torch-config`, plus `--yes` for non-interactive runs.
- Added a `server doctor` readiness check to verification and a "Qdrant binary did not provision" troubleshooting entry (including the operator-supplied-binary path).

## Outcome

The installation doc now describes server-first default provisioning end to end with honest opt-outs and the pure-Python-wheel guarantee. Every command and flag was verified against live `--help`: `install` (`--local-only`, `--skip-torch/--skip-models/--skip-qdrant`, `--no-provision`, `--dry-run`, `--sync`, `--yes`, `--no-torch-config`), `server doctor`, and `server qdrant install --binary`. `mdformat` is a no-op and `pymarkdown --config .pymarkdown.json scan` exits 0.

## Notes

- The two-phase torch wording ("configured, sync pending") matches the live provisioning reporter in `commands/_provision.py`; the `install --dry-run` run confirmed the per-step sync-vocabulary lines.
