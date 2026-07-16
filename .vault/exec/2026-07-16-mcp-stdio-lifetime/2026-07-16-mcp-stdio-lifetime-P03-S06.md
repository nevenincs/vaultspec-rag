---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S06'
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
     The S06 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Add integration tests: spawn a real parent-intermediary-worker chain, kill the intermediary, assert the worker hard-exits within the bound and ## Scope

- `plus a companion EOF-still-primary shutdown test`
- `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add integration tests: spawn a real parent-intermediary-worker chain, kill the intermediary, assert the worker hard-exits within the bound

## Scope

- `plus a companion EOF-still-primary shutdown test`
- `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`

## Description

- Add `test_stdio_lifetime_e2e.py` (integration): spawn a real
  test-runner -> intermediary -> worker chain, kill the intermediary
  after the grace window, assert the worker hard-exits within the bound
  (the research W2 fires-on-death mandate, in real subprocesses).
- Add the EOF-still-primary companion: the real shim entry point
  (`main()` over piped stdio) exits 0 when stdin closes, watchdog armed.

## Outcome

Both tests pass (~10s); ruff, basedpyright green.

## Notes

First run failed by killing the intermediary INSIDE the grace window -
the watchdog pruned the death as spawn-helper noise by design. The test
now waits out the grace before killing; the interaction is documented in
the test body.
