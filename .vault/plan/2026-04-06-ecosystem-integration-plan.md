---
tags:
  - '#plan'
  - '#ecosystem-integration'
date: 2026-04-06
modified: '2026-06-30'
revised: 2026-04-11
related:
  - '[[2026-04-06-ecosystem-integration-adr]]'
  - '[[2026-04-06-ecosystem-integration-research]]'
  - '[[2026-04-11-ecosystem-integration-deep-audit]]'
---

# `ecosystem-integration` `full-scope` plan (revised 2026-04-11)

Implements the companion-package integration model between vaultspec-rag
and vaultspec-core 0.1.7. All upstream blockers (core#36, core#43, core#50,
core#51) have been resolved. Scope expanded from phase-1-only to full
delivery of #54, #47, #48, #55.

## Scope

**Delivered (this PR):**

- #54 (partial): `vaultspec-rag.builtin.md` rule + sync verification
- #47: `.gitattributes` eol=lf completion + renormalization
- #48: pre-commit hook migration to core 0.1.7 canonical pattern
- #55: MCP server registration via core's registry

**Out of scope (separate issues filed):**

- #54 (install/uninstall CLI): deferred — requires further design
- #59 (workspace.py re-implementation): technical debt, pre-beta

## Proposed Changes

Deliver four integration channels between RAG and core: rule enrollment
via sync pipeline, MCP server registration via registry, pre-commit hook
standardization via canonical patterns, and git config normalization.

## Tasks

### Task 1: create `vaultspec-rag.builtin.md` (DONE)

Created `.vaultspec/rules/rules/vaultspec-rag.builtin.md` with CLI
commands, MCP tool signatures, decision guide, data directory contract,
env var namespace. Verified via code review — all signatures match
`mcp_server.py` and `cli.py` exactly.

### Task 2: sync and verify provider enrollment (DONE)

Ran `vaultspec-core sync`. Rule propagated to `.claude/rules/` and
enrolled in `CLAUDE.md` automatically. Body content matches source.

### Task 3: `.gitattributes` eol=lf completion (DONE)

Added `eol=lf` to all text file types: `*.md`, `*.txt`, `*.yml`,
`*.yaml`, `*.toml`, `*.xml`, `*.json`, `*.css`, `*.js`, `*.ts`,
`*.tsx`, `*.html`. Ran `git add --renormalize .`.

### Task 4: pre-commit hook migration (DONE)

Replaced 5 deprecated hooks (`check-naming`, `check-dangling`,
`check-body-links`, `vault-doctor`, `vault-doctor-deep`) with 2
canonical consolidated hooks (`vault-fix`, `spec-check`) using
`uv run --no-sync vaultspec-core` entry prefix. Eliminates fragile
`python -c` import pattern and `python -m` without `--no-sync`.

### Task 5: MCP server registration (DONE)

Created `.vaultspec/rules/mcps/vaultspec-rag.builtin.json` with stdio
server definition (`uv run vaultspec-search-mcp`). Core's `mcp_sync()`
pass merges this into `.mcp.json` on `vaultspec-core sync`.

### Task 6: gitignore cleanup (DONE)

Removed duplicate manual entries superseded by core's managed block.
Core's #50 fix replaced blanket `.vault/` with fine-grained entries
(`.vault/.obsidian/`, `.vault/.trash/`, `.vault/data/`, `.vault/logs/`).

### Task 7: pymarkdown config (DONE)

Added `vaultspec` to `allowed_elements` in `.pymarkdown.json` — required
for `<vaultspec>` tags in core-generated `CLAUDE.md`.

## Verification

- `vaultspec-core sync` propagates rule to all provider directories
- Rule content verified against `mcp_server.py` and `cli.py` (code review)
- `.gitattributes` has `eol=lf` on all text types
- Pre-commit hooks use canonical `uv run --no-sync vaultspec-core` pattern
- MCP definition file exists at `.vaultspec/rules/mcps/vaultspec-rag.builtin.json`
- All pre-commit hooks pass
- Upstream bugs filed: core#54 (sync crash), RAG #59 (workspace.py)
