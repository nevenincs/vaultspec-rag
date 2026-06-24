---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S26'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Remove the quality and benchmark verbs from the production CLI command group

## Scope

- `src/vaultspec_rag/cli/_app.py`

## Description

- Removed the `handle_benchmark` and `handle_quality` command-registration imports and their
  `__all__` entries from the CLI package init, so the `@app.command` decorators no longer run.
- Deleted the `cli/_benchmark.py` and `cli/_quality.py` verb modules.
- Removed the dev-only `benchmark` and `quality` MCP admin tools (and their now-unused
  transport imports) so the agent-facing surface drops the dev tooling too.
- Replaced the CLI help tests with positive removal assertions (the verbs return "No such
  command") and deleted the obsolete `TestBenchmarkAndQualityCommands` delegation suite;
  updated the MCP no-local-fallback tool inventory.

## Outcome

The production CLI now exposes only operator verbs (clean, index, install, search, status,
test, uninstall, plus the server group); `benchmark` and `quality` are gone from both the CLI
and the MCP admin surface. 269 CLI + MCP-fallback tests pass; `ruff` clean; the package
imports with the two verbs absent.

## Notes

`test` is retained: it is the project's sanctioned pytest entry point (testing mandate, CLAUDE
.md), distinct from the dev-only report verbs D9 removes. No blockers.
