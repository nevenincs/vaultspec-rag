---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:265e1a252bbb10db741576ad45965223f26bd24d67051c81f8425d29c27f2853'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# `mcp-stdio-lifetime` `P02` summary

Both P02 Steps (S03, S04) are closed. The watchdog is wired and
operable.

- Modified: `src/vaultspec_rag/server/_main.py`
- Modified: `src/vaultspec_rag/config.py`

## Description

Installed the watchdog on exactly the stdio branch of the entry point
(before `mcp.run`, never on the HTTP daemon or `--help` paths), added
the optional `--parent-pid` explicit watch target, and registered the
kill-switch knob in the `EnvVar` inventory so the module reads it from
the single source of truth. `vaultspec-search-mcp --help` still exits 0
without arming anything.
