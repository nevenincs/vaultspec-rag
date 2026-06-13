---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S42'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# update the human CLI documentation so the readiness verb and install opt-out flags match the live command surface

## Scope

- `docs/cli.md`

## Description

- Rewrote the `install` reference section: server-first default provisioning of torch, models, and the qdrant binary; the pure-Python-wheel + runtime-fetch + verify-before-execute guarantee; and the full opt-out flag table (`--provision/--no-provision`, `--local-only`, `--skip-torch`, `--skip-models`, `--skip-qdrant`) plus the two-phase torch note.
- Added a `server doctor` reference section (per-dependency readiness snapshot, `--json`, exit code, and the token-gated `GET /readiness` route).
- Replaced the stale `server service start` section with a live `server start` section documenting `--local-only`, `--updates/--no-updates`, `--update-delay-ms`, `--repeat-update-delay-s`, `--qdrant/--no-qdrant`, and `--qdrant-auto-provision`.
- Updated the Contents anchor list to add `server doctor` and rename `server service start` to `server start`.

## Outcome

The human CLI reference now matches the live command surface for the server-first verbs and flags in scope. Each was verified against `--help`: `vaultspec-rag install --help` (opt-out flags), `server doctor --help` (`--json`), and `server start --help` (`--local-only`, `--updates`, `--update-delay-ms`, `--repeat-update-delay-s`, `--qdrant`, `--qdrant-auto-provision`). `mdformat` is a no-op and `pymarkdown --config .pymarkdown.json scan` exits 0.

## Notes

- Scope for this Step was the `server doctor` verb, the `install` opt-out flags, and `server start --local-only`; the broader rename of the remaining `server service ...` reference sections (`stop`, `status`, `warmup`, `projects`, `watcher`, `info`, `logs`, `jobs`) to the live `server ...` surface was left untouched to stay within Step scope and avoid colliding with other Steps in this shared plan. Those sections remain pre-existing and were not introduced by this Step.
