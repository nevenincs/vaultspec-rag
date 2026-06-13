---
tags:
  - '#audit'
  - '#ecosystem-integration'
date: 2026-04-11
modified: '2026-04-11'
related:
  - '[[2026-04-06-ecosystem-integration-adr]]'
  - '[[2026-04-06-ecosystem-integration-plan]]'
  - '[[2026-04-11-ecosystem-integration-review-audit]]'
---

# `ecosystem-integration` Deep Audit (post core 0.1.7)

Comprehensive integration audit after all core blockers cleared.
Five parallel agents audited pre-commit hooks, MCP registry, CLI
overlap, git config, and builtin rule accuracy.

## Pre-commit hooks

PC-1 | CRITICAL | 3 hooks used fragile `python -c` import pattern
`check-naming`, `check-dangling`, `check-body-links` invoked core via
`python -c "from vaultspec_core.cli import app; app()"`. Breaks if core
refactors CLI internals.
**Status:** FIXED — replaced with `vault-fix` consolidated hook.

PC-2 | CRITICAL | 5 hooks used deprecated IDs
All 5 vault hooks carried IDs on core's deprecation list.
**Status:** FIXED — collapsed to `vault-fix` + `spec-check`.

PC-3 | HIGH | 2 hooks missing `--no-sync` flag
`vault-doctor` and `vault-doctor-deep` used `uv run` without `--no-sync`,
triggering dependency resolution on every commit.
**Status:** FIXED — canonical pattern uses `--no-sync`.

## MCP registry

MCP-1 | CRITICAL | No MCP definition file
`.vaultspec/rules/mcps/` directory did not exist. RAG's MCP server was
not registered via core's new registry.
**Status:** FIXED — created `vaultspec-rag.builtin.json`.

MCP-2 | LOW | No hand-rolled `.mcp.json` manipulation
Grep confirmed zero references to `.mcp.json` in RAG source. Clean.
**Status:** PASS.

## CLI and coupling

CLI-1 | PASS | CLI entry points — zero overlap with core
RAG commands (`index`, `search`, `status`, `server`, `benchmark`,
`quality`, `test`) do not shadow any core commands.

CLI-2 | PASS | Core imports — all via public API
RAG imports `VaultSpecConfig`, `get_config`, `scan_vault`,
`parse_vault_metadata`, `VaultGraph`, `get_vault_metrics`. No CLI
internals imported.

CLI-3 | CRITICAL | `workspace.py` re-implements core's workspace resolution
~313 lines mirroring `vaultspec_core.config.workspace` — `WorkspaceLayout`,
`GitInfo`, `LayoutMode`, `discover_git`, `resolve_workspace`. Silent drift
risk if core changes workspace logic.
**Status:** DEFERRED — filed as #59. Out of scope for this PR, pre-beta.

CLI-4 | LOW | Hardcoded `.vault/data/search-data` path
Not derived from core API. Minor drift risk.
**Status:** ACCEPTED — stable convention.

## Git configuration

GIT-1 | HIGH | Renormalization not fully applied
166 files had CRLF in working tree after `.gitattributes` change.
**Status:** FIXED — ran `git add --renormalize .`

GIT-2 | MEDIUM | 3 duplicate `.gitignore` entries
`.vault/.obsidian/`, `.vault/logs/`, `.vault/data/search-data/` duplicated
between manual section and managed block.
**Status:** FIXED — removed manual duplicates.

GIT-3 | LOW | 7 files lack explicit `eol=lf` rule
`justfile`, `LICENSE`, `.env.example`, `uv.lock` etc. fall through to
`text=auto`. Acceptable — these are edge cases.
**Status:** ACCEPTED.

## Builtin rule

RULE-1 | PASS | All CLI commands verified against `cli.py`
10 commands documented, all confirmed via `@app.command()` / subapp decorators.

RULE-2 | PASS | All MCP tool signatures verified against `mcp_server.py`
6 tools + 1 resource + 1 prompt. All parameter names, types, defaults match.

RULE-3 | PASS | Env vars and port default verified against `config.py`
4 user-facing vars documented. Port default 8766 confirmed.

RULE-4 | PASS | Synced copy body content identical to source

## Upstream issues filed

- core#50 (CLOSED): `.vault/` removed from managed gitignore block
- core#51 (CLOSED): `.vaultspec/` tracking mode — merged into #50
- core#54 (OPEN): `sync all` CLI crash — `resource_labels` missing `mcps`
- RAG #59 (OPEN): `workspace.py` re-implementation — import core instead
