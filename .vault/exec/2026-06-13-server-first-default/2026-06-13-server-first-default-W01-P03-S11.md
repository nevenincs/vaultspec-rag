---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S11'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# default the qdrant-binary pre-start guard to run by default and skip it under --local-only so a default start fails fast on a missing binary

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Change the pre-start qdrant-binary guard from `if qdrant:` (run only on an
  explicit `--qdrant`) to `if not local_only and qdrant is not False:` so the guard
  runs by default, matching the server-first default backend.
- Skip the guard when `--local-only` is set or `--no-qdrant` is explicitly passed,
  so the local opt-out never touches the server binary.
- Update the `_ensure_qdrant_binary` docstring from "before a --qdrant start" to
  "before a server-mode start", naming the default-runs/local-only-skips contract.

## Outcome

- A default `server start` (no flags) now resolves the managed Qdrant binary before
  spawning the daemon and, when it is absent and `--qdrant-auto-provision` was not
  given, fails fast with the loud, actionable message naming
  `vaultspec-rag server qdrant install` and the auto-provision consent flag.
- `server start --local-only` and `server start --no-qdrant` skip the binary guard
  entirely and proceed to the on-disk store path.
- Persona check (cli-operability-needs-persona-tests): ran
  `uv run --no-sync vaultspec-rag server start --help` and confirmed the human help
  renders `--local-only` ("Use the on-disk local store instead of the default
  managed Qdrant server...") and the reframed `--qdrant` help naming server mode as
  the default and `--local-only` as the local-store selector. The start surface
  reads correctly for an operator in human mode.
- `ruff check` and `ty check` clean on `src/vaultspec_rag/cli/_service_lifecycle.py`.

## Notes

The guard condition `not local_only and qdrant is not False` deliberately treats the
default (`qdrant is None`) and the explicit `--qdrant` (`qdrant is True`) cases
identically as "server mode", and treats both `--local-only` and `--no-qdrant` as
local-mode skips, mirroring `effective_server_mode()` (`qdrant_server and not local_only`) on the CLI side. The daemon still resolves the authoritative effective
mode from env; this guard is the fast-fail front door so a default start does not
spawn a daemon that will then abort on a missing binary.
