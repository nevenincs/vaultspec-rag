---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S37'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---




# reframe the service-mode doc from local-first server-optional to server-first local-explicit and document the readiness verb

## Scope

- `docs/service-mode.md`

## Description

- Added a "Server-first, local-explicit" section reframing the page from "local-first, server-optional": server mode is the default supervised backend; local mode is a first-class opt-out for CI, air-gapped, and small-project hosts via `--local-only` or `VAULTSPEC_RAG_LOCAL_ONLY=1`.
- Documented that `server start` defaults to server mode, prints the install command (not an opaque failure) when the Qdrant binary is missing, and accepts `--local-only`, `--qdrant/--no-qdrant`, and `--qdrant-auto-provision`.
- Added a "Check readiness" section for `server doctor` (per-dependency torch/models/qdrant snapshot, `--json`) and noted the token-gated `GET /readiness` route serving the same snapshot.
- Aligned automatic-update prose with the live surface (`--updates/--no-updates`, `--update-delay-ms`, `--repeat-update-delay-s`, and the `server updates status/start/stop/timing` subcommands), replacing the prior `--watch`/`server service watcher` names.
- Corrected service-control commands to the live `server` surface (`server start/stop/status/logs/jobs/projects/warmup`) and added a "Manage the Qdrant server binary" section (`server qdrant status/install`, including `--binary`).
- Reframed the "Server will not start" troubleshooting entry around the loud, actionable failure contract and the `--local-only` fallback.

## Outcome

The service-mode doc now reads server-first, local-explicit, documents the `server doctor` readiness verb and the `/readiness` route, and explains when to choose `--local-only`. Every command and flag was verified against live `--help`: `server start` (`--local-only`, `--updates/--no-updates`, `--update-delay-ms`, `--repeat-update-delay-s`, `--qdrant/--no-qdrant`, `--qdrant-auto-provision`), `server doctor` (`--json`), `server updates`, `server logs`, `server jobs`, `server projects`, `server qdrant`; the token-gated `/readiness` route was confirmed in `server/_routes.py`. `mdformat` is a no-op and `pymarkdown --config .pymarkdown.json scan` exits 0.

## Notes

- The prior doc described a `server service ...` / `--watch` command surface that the live CLI no longer exposes; the sections this Step touched were corrected to the live `server ...` / `--updates` surface so no fictional commands remain in the reframed page. The `/readiness` route is token-gated (`require_token`), matching the ADR.
