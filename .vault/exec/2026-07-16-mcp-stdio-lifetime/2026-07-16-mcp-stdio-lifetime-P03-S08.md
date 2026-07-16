---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S08'
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
     The S08 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Document the stdio lifetime contract, the --parent-pid override, and the VAULTSPEC_RAG_STDIO_WATCHDOG knob in the service reference docs and ## Scope

- `docs/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Document the stdio lifetime contract, the --parent-pid override, and the VAULTSPEC_RAG_STDIO_WATCHDOG knob in the service reference docs

## Scope

- `docs/`

## Description

- Add a "Stdio server lifetime" section to `docs/mcp.md` describing the
  self-reap contract, the stderr JSON exit line, exit code 0, and the
  two knobs (`--parent-pid`, `VAULTSPEC_RAG_STDIO_WATCHDOG=0`).
- Register the knob in the `docs/configuration.md` env table (new
  "Stdio MCP lifetime" section); mdformat pass applied (CI markdown
  gate).

## Outcome

Docs updated and mdformat-clean.

## Notes

None.
