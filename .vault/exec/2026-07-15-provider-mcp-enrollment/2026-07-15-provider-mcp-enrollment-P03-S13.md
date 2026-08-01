---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:fef44454938e6640ad9b0b0cfb7838dcd8c091d5a1ceae03476be0ea29b259f1'
step_id: 'S13'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Verify wheel metadata console entry point canonical builtin Core floor and installed-package acceptance

## Scope

- `src/vaultspec_rag/tests/test_packaging_metadata.py, tests/smoke_check.py, src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/tests/test_install_mcp_extra.py, src/vaultspec_rag/tests/test_cli.py, and src/vaultspec_rag/tests/test_server_doctor.py`

## Description

- Assert the installed console metadata targets the supported stdio server.
- Assert the installed package carries the exact canonical mode-aware MCP builtin.
- Build local Core and RAG wheels into an isolated artifact directory.
- Run the smoke checker with only those wheels and their resolved dependencies.
- Invoke the installed RAG CLI and verify canonical Claude Code and Codex project targets.
- Preserve structured install reporting when MCP-extra inspection meets malformed TOML.
- Return the documented configuration-error exit code for malformed consumer metadata.
- Enroll the doctor fixture through the provider manifest before asserting deployed drift.

## Outcome

The local RAG wheel contains the canonical MCP source, registers both console scripts,
and installs successfully beside the fixed Core feature wheel. The isolated installed
CLI enrolls identical `uvx --from vaultspec-rag[mcp]` launches in Claude Code JSON and
Codex TOML project targets. Five focused package-metadata tests and all smoke checks
pass. The built RAG wheel resolves Core 0.1.44 from the public index without a local
source override.

The full unit gate passes 1,413 tests. Its first passes exposed two stale assumptions at
the new lifecycle boundary: malformed TOML escaped before the established report and exit
mapping, and a doctor fixture requested no MCP source before editing a deployed entry.
Both now use the real provider contract and have focused regression coverage.

## Notes

Initial validation used Core commit `4be49ee0` from the isolated Core campaign worktree.
Final acceptance uses the public Core 0.1.44 wheel, verifies the exact `>=0.1.44`
distribution floor, and runs the installed RAG CLI from its built wheel in an isolated
environment.
