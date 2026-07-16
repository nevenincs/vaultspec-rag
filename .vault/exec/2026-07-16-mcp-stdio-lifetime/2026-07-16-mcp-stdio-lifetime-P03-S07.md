---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S07'
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
     The S07 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Add ADR regression guards: fresh-interpreter import of the watchdog module loads neither torch nor mcp, and the HTTP daemon path never references the watchdog installer and ## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add ADR regression guards: fresh-interpreter import of the watchdog module loads neither torch nor mcp, and the HTTP daemon path never references the watchdog installer

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Add `TestStdioLifetimeWatchdogStaysThin` to the ADR regression suite:
  a fresh-interpreter import of the watchdog module must load neither
  `torch` nor `mcp`, and a source scan pins the installer to the stdio
  branch of `main` only (absent from the HTTP branch and `_lifespan`).

## Outcome

30 regression tests pass; ruff, basedpyright green.

## Notes

None.
