---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S03'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace mcp-stdio-lifetime with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S03 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Wire install_stdio_lifetime_watchdog into the stdio branch before mcp.run, add the optional --parent-pid argument, and keep HTTP daemon mode and --help paths watchdog-free and ## Scope

- `src/vaultspec_rag/server/_main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Wire install_stdio_lifetime_watchdog into the stdio branch before mcp.run, add the optional --parent-pid argument, and keep HTTP daemon mode and --help paths watchdog-free

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Add the optional `--parent-pid` argument to the console-script argparse
  surface (stdio-only semantics documented in the help text).
- Install the watchdog in the stdio branch before `mcp.run`, with the
  stdio-only rationale stated at the call site; HTTP daemon mode and
  `--help` never reach the installer.

## Outcome

ruff, basedpyright, ty green; `vaultspec-search-mcp --help` still exits 0
without arming anything (packaging smoke contract preserved).

## Notes

None.
