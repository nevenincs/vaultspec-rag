---
generated: true
tags:
  - '#index'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - '[[2026-07-16-mcp-stdio-lifetime-P01-S01]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P01-S02]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P01-summary]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P02-S03]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P02-S04]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P02-summary]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P03-S05]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P03-S06]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P03-S07]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P03-S08]]'
  - '[[2026-07-16-mcp-stdio-lifetime-P03-summary]]'
  - '[[2026-07-16-mcp-stdio-lifetime-adr]]'
  - '[[2026-07-16-mcp-stdio-lifetime-audit]]'
  - '[[2026-07-16-mcp-stdio-lifetime-plan]]'
  - '[[2026-07-16-mcp-stdio-lifetime-research]]'
---

# `mcp-stdio-lifetime` feature index

Auto-generated index of all documents tagged with `#mcp-stdio-lifetime`.

## Documents

### adr

- `2026-07-16-mcp-stdio-lifetime-adr` - `mcp-stdio-lifetime` adr: `The stdio shim owns its lifetime: ancestor-chain watchdog behind stdin EOF` | (**status:** `accepted`)

### audit

- `2026-07-16-mcp-stdio-lifetime-audit` - `mcp-stdio-lifetime` audit: `stdio lifetime watchdog implementation review`

### exec

- `2026-07-16-mcp-stdio-lifetime-P01-S01` - Create the watchdog module with ctypes kernel32 bindings (full argtypes and restype), Toolhelp32 ancestor-chain discovery bounded and cycle-safe, creation-time monotonicity PID-reuse guard, and immediate SYNCHRONIZE handle acquisition
- `2026-07-16-mcp-stdio-lifetime-P01-S02` - Add watchdog arming in the same module: startup grace window that prunes ancestors dead during grace, wait-any watchdog daemon thread, structured stderr line naming the dead ancestor, os._exit(0) trigger, POSIX getppid reparent poll fallback, and the VAULTSPEC_RAG_STDIO_WATCHDOG disable knob
- `2026-07-16-mcp-stdio-lifetime-P01-summary` - `mcp-stdio-lifetime` `P01` summary
- `2026-07-16-mcp-stdio-lifetime-P02-S03` - Wire install_stdio_lifetime_watchdog into the stdio branch before mcp.run, add the optional --parent-pid argument, and keep HTTP daemon mode and --help paths watchdog-free
- `2026-07-16-mcp-stdio-lifetime-P02-S04` - Register the VAULTSPEC_RAG_STDIO_WATCHDOG env knob in the config env inventory following the existing knob conventions
- `2026-07-16-mcp-stdio-lifetime-P02-summary` - `mcp-stdio-lifetime` `P02` summary
- `2026-07-16-mcp-stdio-lifetime-P03-S05` - Add unit tests for ancestor discovery guards, disable knob, parent-pid override handling, and non-stdio inertness
- `2026-07-16-mcp-stdio-lifetime-P03-S06` - Add integration tests: spawn a real parent-intermediary-worker chain, kill the intermediary, assert the worker hard-exits within the bound
- `2026-07-16-mcp-stdio-lifetime-P03-S07` - Add ADR regression guards: fresh-interpreter import of the watchdog module loads neither torch nor mcp, and the HTTP daemon path never references the watchdog installer
- `2026-07-16-mcp-stdio-lifetime-P03-S08` - Document the stdio lifetime contract, the --parent-pid override, and the VAULTSPEC_RAG_STDIO_WATCHDOG knob in the service reference docs
- `2026-07-16-mcp-stdio-lifetime-P03-summary` - `mcp-stdio-lifetime` `P03` summary

### plan

- `2026-07-16-mcp-stdio-lifetime-plan` - `mcp-stdio-lifetime` plan

### research

- `2026-07-16-mcp-stdio-lifetime-research` - `mcp-stdio-lifetime` research: `stdio shim orphan leak and lifetime hardening on Windows`
