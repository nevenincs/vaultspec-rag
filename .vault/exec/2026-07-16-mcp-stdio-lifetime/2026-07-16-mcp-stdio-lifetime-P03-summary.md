---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# `mcp-stdio-lifetime` `P03` summary

All four P03 Steps (S05-S08) are closed. The watchdog is proven
end-to-end and documented.

- Created: `src/vaultspec_rag/tests/test_stdio_lifetime.py`
- Created: `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`
- Modified: `src/vaultspec_rag/tests/test_adr_regression.py`
- Modified: `docs/mcp.md`
- Modified: `docs/configuration.md`

## Description

Unit tests (22) cover the walk guards, kill switch, installer, and real
Windows handle semantics; the integration pair proves fires-on-death in
a real spawned chain and that stdin EOF still exits the real shim
cleanly; ADR regression guards pin the no-torch/no-mcp import graph and
the stdio-only install site. Docs gained the stdio lifetime contract
section and the knob table entry (mdformat clean). Verification: full
unit suite 1409 passed; manual kill-the-top-uv.exe repro reaps the
whole chain with the structured stderr line. Full integration suite hit
the known GPU-test timeout with the resident service running; the
feature's own integration tests pass.
