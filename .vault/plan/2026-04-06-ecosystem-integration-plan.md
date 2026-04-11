---
tags:
  - '#plan'
  - '#ecosystem-integration'
date: 2026-04-06
revised: 2026-04-11
related:
  - '[[2026-04-06-ecosystem-integration-adr]]'
  - '[[2026-04-06-ecosystem-integration-research]]'
---

# `ecosystem-integration` `phase-1` plan (revised 2026-04-11)

Implements the unblocked portion of the companion-package integration
model. Scope reduced to items with zero upstream core dependencies.
Derived from the accepted ADR (scope revision 2026-04-11).

## Scope

**In scope (this PR):**

- #54 (partial): rule authoring + CLAUDE.md enrollment + sync verification
- #47: `.gitattributes` eol=lf completion + line ending normalization

**Deferred (blocked on core):**

- #54 (install/uninstall CLI) — awaits core#43, core#36
- #48 (pre-commit hook standardization) — awaits core#36
- #55 (MCP registry enrollment) — awaits core#43

## Proposed Changes

Create a builtin rule that teaches LLMs about RAG capabilities and when
to use RAG vs core. Enroll it in CLAUDE.md and verify core's sync
propagates it. Fix `.gitattributes` to enforce `eol=lf` on all text file
types and renormalize existing files.

## Tasks

### Task 1: create `vaultspec-rag.builtin.md`

Create `.vaultspec/rules/rules/vaultspec-rag.builtin.md` containing:

- Companion model explanation (RAG is a peer to core, not a plugin)
- RAG CLI command reference: `index`, `search`, `status`, `server`,
  `benchmark`, `quality`, `test`
- MCP tool reference (6 tools): `search_vault`, `search_codebase`,
  `get_index_status`, `get_code_file`, `reindex_vault`,
  `reindex_codebase`; 1 resource: `vault://{doc_id}`
- MCP entry points: `vaultspec-search-mcp` (console script),
  `vaultspec-rag server start` (HTTP mode)
- Decision guide: when to use `vaultspec-rag search` (semantic) vs
  `vaultspec-core vault list/check` (structured CRUD)
- Data directory contract: `.vault/data/search-data/` is RAG-managed,
  gitignored, invisible to core's scanner
- Env var namespace: `VAULTSPEC_RAG_*` (documented in rule)

**Source verification needed:** read `src/vaultspec_rag/mcp_server.py`
for exact MCP tool signatures; read `pyproject.toml` for entry points.

### Task 2: sync and verify provider enrollment

Run `vaultspec-core sync` to propagate the new rule to all configured
providers. Core's sync pipeline reads `.vaultspec/rules/rules/` from
disk and distributes to provider-specific directories (`.claude/rules/`,
etc.). Enrollment in provider configs (e.g., `CLAUDE.md`) is managed
entirely by core's sync — we do NOT manually edit provider configs.

Verify the rule lands in at least one provider directory after sync.
This confirms the companion-package seeding mechanism works as designed.

### Task 3: `.gitattributes` eol=lf completion (#47)

Current `.gitattributes` has `text` without `eol=lf` for:

- `*.md`, `*.txt` (documentation)
- `*.yml`, `*.yaml`, `*.toml`, `*.xml` (config)
- `*.json`, `*.css`, `*.js`, `*.ts`, `*.tsx` (web)
- `*.html` (uses `text diff=html`, no eol)

Add `eol=lf` to all text file types. Then run
`git add --renormalize .` to normalize existing files in the index.

**Note:** the `.vaultspec/rules/` CRLF drift visible in `git status` is
exactly this issue — renormalization will fix it.

## Parallelization

- Tasks 1-2 are sequential (rule must exist before sync)
- Task 3 is independent of tasks 1-2 and can run in parallel

Best strategy: implement tasks 1-2 sequentially, task 3 can be done
at any point.

## Verification

- `vaultspec-core sync` propagates rule to provider directories
- Rule content matches MCP tool signatures from `mcp_server.py`
- Provider configs (e.g., `CLAUDE.md`) updated by core's sync pipeline
- `.gitattributes` has `eol=lf` on all text types
- `git diff` after renormalize shows LF normalization on affected files
- All existing tests pass (`vaultspec-rag test`)
- Pre-commit hooks (ruff, ty) pass on modified files
