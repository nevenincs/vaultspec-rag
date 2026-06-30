---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-06-30'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-4-cli-rewrite`

Rewrite `handle_index` in `cli.py` to construct a single
`RichProgressReporter` from the module `console`, drive init sub-steps
through it explicitly, and thread it into both indexers.

- Modified: `src/vaultspec_rag/cli.py`

## Description

The coarse three-task `rich.Progress` is gone. A `RichProgressReporter`
is entered as a context manager; each init sub-step
(`resolve workspace`, `open store`, `load embedding model`) emits its own
`phase_start`/`advance`/`phase_end`. Vault and codebase phases are then
driven by the indexers themselves through the same reporter instance.

Dry-run and MCP-delegation branches are unchanged beyond returning
early before the reporter is constructed. The dry-run branch has no
indexer call sites and needs no reporter. The synthetic-corpus quality
helper at the bottom of the CLI uses a local `NullProgressReporter`.

Old `console.log` summary lines for per-phase counts are removed; the
final summary table after the context exits is preserved verbatim.

## Tests

CLI unit tests (`test_cli.py`, `test_cli_warmup.py`) still green — the
reporter wiring doesn't break any CLI entry point.
