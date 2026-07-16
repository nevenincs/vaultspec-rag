---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S05'
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
     The S05 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Add unit tests for ancestor discovery guards, disable knob, parent-pid override handling, and non-stdio inertness and ## Scope

- `src/vaultspec_rag/tests/test_stdio_lifetime.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add unit tests for ancestor discovery guards, disable knob, parent-pid override handling, and non-stdio inertness

## Scope

- `src/vaultspec_rag/tests/test_stdio_lifetime.py`

## Description

- Add `test_stdio_lifetime.py` unit coverage: pure ancestor-walk guards
  (chain order, missing entry, pid 0, self-parent, cycle, depth bound),
  env kill-switch semantics, installer disable/arm behavior (named daemon
  thread), and Windows-only real-handle assertions (parent chain
  discovery, explicit-pid dedupe and skip, creation-time monotonicity)
  against genuine kernel32 calls with no mocks.
- Add a `grace_seconds` parameter to `install_stdio_lifetime_watchdog` so
  tests control the arming window without patching module constants.

## Outcome

22 tests pass; ruff, basedpyright, ty green.

## Notes

An initial dead-PID assertion used PID 4 (openable here) and then a
zombie child (openable while the Popen handle lives); the stable choice
is PID 3, which can never name a Windows process.
