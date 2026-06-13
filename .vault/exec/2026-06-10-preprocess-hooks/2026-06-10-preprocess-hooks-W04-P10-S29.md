---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S29'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Register the preprocess sub-app on the CLI root (D13)

## Scope

- `src/vaultspec_rag/cli/__init__.py`

## Description

Created `preprocess_app` in `cli/_app.py` (beside the server sub-apps), registered it on
the root via `app.add_typer(preprocess_app, name="preprocess")`, added it to `__all__`, and
imported the three handlers in `cli/__init__.py` so their `@preprocess_app.command`
decorators fire at package import (D13).

## Outcome

`vaultspec-rag preprocess {list,check,run-one}` is reachable from the root CLI; help lists
the group.

## Notes

Mirrors the established sub-app nesting pattern (server/mcp/projects/watcher).
