---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S01'
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
     The S01 and 2026-07-16-mcp-stdio-lifetime-plan placeholders are machine-filled by
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
     The Create the watchdog module with ctypes kernel32 bindings (full argtypes and restype), Toolhelp32 ancestor-chain discovery bounded and cycle-safe, creation-time monotonicity PID-reuse guard, and immediate SYNCHRONIZE handle acquisition and ## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Create the watchdog module with ctypes kernel32 bindings (full argtypes and restype), Toolhelp32 ancestor-chain discovery bounded and cycle-safe, creation-time monotonicity PID-reuse guard, and immediate SYNCHRONIZE handle acquisition

## Scope

- `src/vaultspec_rag/server/_stdio_lifetime.py`

## Description

- Create `src/vaultspec_rag/server/_stdio_lifetime.py` with the module
  docstring stating the lifetime contract and thin-client constraints.
- Bind kernel32 (`CreateToolhelp32Snapshot`, `Process32First/Next`,
  `OpenProcess`, `CloseHandle`, `GetProcessTimes`, `WaitForSingleObject`,
  `WaitForMultipleObjects`) with full argtypes/restype under a
  `sys.platform == "win32"` guard.
- Implement `_walk_ancestor_pids` as a pure, cross-platform, bounded and
  cycle-safe parent-map walk (unit-testable without Windows APIs).
- Implement `_snapshot_processes`, `_creation_time`, `_open_process`, and
  `open_ancestor_handles` with immediate SYNCHRONIZE handle acquisition,
  creation-time monotonicity as the PID-reuse guard, and explicit
  `--parent-pid` extras watched ahead of discovery.
- Add the `watchdog_disabled` env-knob probe (`VAULTSPEC_RAG_STDIO_WATCHDOG`).

## Outcome

Module compiles clean: ruff check/format, basedpyright, and ty all pass.
Arming/trigger logic lands in the next Step.

## Notes

The explicit-signature mandate exists because the research prototype's
undeclared ctypes bindings failed silently (research finding W2).
