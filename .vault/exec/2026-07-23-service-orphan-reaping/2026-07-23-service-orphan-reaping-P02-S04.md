---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S04'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-orphan-reaping with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Add a top-level entrypoint os.\_exit backstop on any startup exception escaping uvicorn.run and ## Scope

- `src/vaultspec_rag/server/_main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add a top-level entrypoint os.\_exit backstop on any startup exception escaping uvicorn.run

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Add `import os` to the daemon entrypoint module.
- Track a `daemon_exit_code` around `uvicorn.run`, set to 1 by an `except`
  branch when the run raises.
- In the entrypoint `finally`, after component close and log-capture drain,
  force `os._exit` for the standalone daemon (gated on `_daemon_process`),
  preserving the log-drain-contract raise for the in-process embedded-reuse
  host.

## Outcome

A startup failure that escapes `uvicorn.run` without the lifespan's own
`os._exit` firing - the port-bind sibling, or any error uvicorn surfaces before
the lifespan runs - now forces a prompt daemon exit instead of a wedged
interpreter shutdown. ruff, ty, basedpyright, and the complexity gate clean.
Committed in `57bdee8f`.

## Notes

Covers the one failure class the lifespan guard cannot: a failed port bind never
reaches the lifespan, so the exit backstop must live at the entrypoint. Off the
standalone daemon this is inert and the embedded-reuse drain contract is
unchanged.
