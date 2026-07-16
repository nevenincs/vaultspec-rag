---
tags:
  - '#plan'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
tier: L2
related:
  - '[[2026-07-16-mcp-stdio-lifetime-adr]]'
  - '[[2026-07-16-mcp-stdio-lifetime-research]]'
---

# `mcp-stdio-lifetime` plan

### Phase `P01` - Watchdog module

Build the stdlib-only stdio lifetime watchdog: Windows ancestor-chain handle wait plus POSIX reparent poll, hard-exit backstop behind stdin EOF.

- [x] `P01.S01` - Create the watchdog module with ctypes kernel32 bindings (full argtypes and restype), Toolhelp32 ancestor-chain discovery bounded and cycle-safe, creation-time monotonicity PID-reuse guard, and immediate SYNCHRONIZE handle acquisition; `src/vaultspec_rag/server/_stdio_lifetime.py`.
- [x] `P01.S02` - Add watchdog arming in the same module: startup grace window that prunes ancestors dead during grace, wait-any watchdog daemon thread, structured stderr line naming the dead ancestor, os._exit(0) trigger, POSIX getppid reparent poll fallback, and the VAULTSPEC_RAG_STDIO_WATCHDOG disable knob; `src/vaultspec_rag/server/_stdio_lifetime.py`.

### Phase `P02` - Wiring and configuration

Install the watchdog on exactly the stdio branch of the shim entry point and expose the operator surface: an optional parent-pid override and the env disable knob registered with the config env inventory.

- [x] `P02.S03` - Wire install_stdio_lifetime_watchdog into the stdio branch before mcp.run, add the optional --parent-pid argument, and keep HTTP daemon mode and --help paths watchdog-free; `src/vaultspec_rag/server/_main.py`.
- [x] `P02.S04` - Register the VAULTSPEC_RAG_STDIO_WATCHDOG env knob in the config env inventory following the existing knob conventions; `src/vaultspec_rag/config.py`.

### Phase `P03` - Tests and regression guards

Prove the watchdog end-to-end in real subprocesses (the research W2 mandate), pin the ADR invariants as regression guards, and document the operator knobs.

- [x] `P03.S05` - Add unit tests for ancestor discovery guards, disable knob, parent-pid override handling, and non-stdio inertness; `src/vaultspec_rag/tests/test_stdio_lifetime.py`.
- [x] `P03.S06` - Add integration tests: spawn a real parent-intermediary-worker chain, kill the intermediary, assert the worker hard-exits within the bound; `plus a companion EOF-still-primary shutdown test; `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`.
- [x] `P03.S07` - Add ADR regression guards: fresh-interpreter import of the watchdog module loads neither torch nor mcp, and the HTTP daemon path never references the watchdog installer; `src/vaultspec_rag/tests/test_adr_regression.py`.
- [x] `P03.S08` - Document the stdio lifetime contract, the --parent-pid override, and the VAULTSPEC_RAG_STDIO_WATCHDOG knob in the service reference docs; `docs/`.

## Description

Implements the accepted mcp-stdio-lifetime ADR: the stdio MCP shim
(`vaultspec-search-mcp`) gains a self-defense lifetime backstop so orphaned
`uv -> launcher -> python` chains stop accumulating on Windows. A new
stdlib-only module discovers the shim's ancestor chain at startup, takes
SYNCHRONIZE handles immediately (PID-reuse safe), arms a wait-any watchdog
daemon thread after a short grace window, and hard-exits (`os._exit(0)`)
when any watched ancestor dies. stdin EOF remains the primary shutdown
path; POSIX gets a coarse reparent poll. The watchdog installs only on the
stdio branch of the entry point, never in the HTTP daemon, honoring the
thin-client and optional-mcp parent decisions. Authorizing decision and
grounding research are in the frontmatter chain.

## Steps

## Parallelization

Phases are sequential: P01 delivers the module P02 wires and P03 tests.
Within P01, S01 precedes S02 (same file, S02 builds on S01's bindings).
Within P02, S03 and S04 touch different files and may run in parallel.
Within P03, S05, S06, S07, and S08 are independent once P02 lands and may
run in parallel.

## Verification

- The integration chain-kill test passes on Windows: a real spawned worker
  exits within the bound after its intermediary is killed, and the
  EOF-still-primary test confirms clean stdin shutdown is unaffected.
- Fresh-interpreter regression guards pass: importing the watchdog module
  loads neither `torch` nor `mcp`, and the HTTP daemon path installs no
  watchdog.
- The full unit suite, lint (ruff), and type gates (basedpyright, ty) are
  green locally; GPU-adjacent suites run locally per project policy.
- Manual verification: spawn `uv run vaultspec-search-mcp`, kill the top
  uv.exe, observe the worker reap itself with the structured stderr line
  (the research L5 scenario no longer leaks).
- Plan completion: every Step row closed via the plan CLI.
