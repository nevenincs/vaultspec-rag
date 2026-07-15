---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S13'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Verify wheel metadata console entry point canonical builtin Core floor and installed-package acceptance

## Scope

- `src/vaultspec_rag/tests/test_packaging_metadata.py and tests/smoke_check.py`

## Description

- Assert the installed console metadata targets the supported stdio server.
- Assert the installed package carries the exact canonical mode-aware MCP builtin.
- Build local Core and RAG wheels into an isolated artifact directory.
- Run the smoke checker with only those wheels and their resolved dependencies.
- Invoke the installed RAG CLI and verify canonical Claude Code and Codex project targets.

## Outcome

The local RAG wheel contains the canonical MCP source, registers both console scripts,
and installs successfully beside the fixed Core feature wheel. The isolated installed
CLI enrolls identical `uvx --from vaultspec-rag[mcp]` launches in Claude Code JSON and
Codex TOML project targets. Four focused package-metadata tests and all smoke checks
pass.

## Notes

This Step remains open until the fixed Core release is published. At that point the
released Core floor assertion and a published-package rerun will complete the acceptance
evidence. Local validation currently uses Core commit `4be49ee0` from the isolated Core
campaign worktree.
