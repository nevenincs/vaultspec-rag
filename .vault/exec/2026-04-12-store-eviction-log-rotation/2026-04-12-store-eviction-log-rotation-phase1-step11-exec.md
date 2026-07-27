---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: '2026-04-12'
modified: '2026-07-27'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

## Description

### Goal

Lint the full modified surface and update user-facing docs for the
four new config knobs, the `service projects list|evict` CLI
subcommands, and the rotating log handler.

### Files touched

- `src/vaultspec_rag/README.md`
- `CHANGELOG.md`

### What was done

- Extended the env-vars table with
  `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS`,
  `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`,
  `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`, and
  `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` with their ADR D8 defaults.
- Added new README subsections **Project slot eviction** and
  **Log rotation** under the Service management section covering
  idle-TTL + LRU semantics, the structured `registry_full` error
  shape, CLI exit codes (0/1/2/3), and the `DaemonRotatingFileHandler`
  `dup2` invariant.
- Updated the CLI tree diagram to show the new
  `server service projects list` and
  `server service projects evict` subcommands.
- Added a new `## Unreleased` section to CHANGELOG.md with four
  bullets summarizing the `#45` deliverables.
- `pre-commit run --all-files` reformatted the README table column
  widths (mdformat) and then re-ran clean on every hook.

## Outcome

### Test results

- `pre-commit run --all-files` â€” all hooks green (ruff,
  ruff-format, taplo, ty, vault fix, mdformat-check,
  pymarkdown, provider artifacts, spec check).

### Commit hash

`acb9d69 docs: document service eviction and log rotation`

## Notes

### Deviations

None.

### Time spent

~10 minutes.
