---
tags:
  - '#adr'
  - '#ecosystem-integration'
date: 2026-04-06
related:
  - '[[2026-04-06-ecosystem-integration-research]]'
  - '[[2026-04-06-ecosystem-integration-plan]]'
  - '[[2026-04-02-service-graph-adr]]'
---

# `ecosystem-integration` adr: `companion-package-model` | (**status:** `accepted`)

## Problem Statement

vaultspec-rag and vaultspec-core share the same workspace (`.vault/`,
`.vaultspec/`) but have no formal integration contract. Core's rule system
has zero awareness of RAG, RAG has no `install` command, and `.vault/data/`
is not defended in core's gitignore or scanner. LLMs operating under
vaultspec receive no guidance on when to use RAG (semantic search) vs core
(structured vault CRUD). The two packages coexist by accident, not by design.

## Considerations

- **CLI compatibility:** entry points (`vaultspec-core`, `vaultspec-rag`,
  `vaultspec-mcp`, `vaultspec-search-mcp`) are already distinct. No conflict.
- **Config namespaces:** core uses `VAULTSPEC_*`, RAG uses `VAULTSPEC_RAG_*`.
  Clean separation. RAG proxies to core's `VaultSpecConfig` for workspace root.
- **Sync pipeline:** core's `sync` reads `.vaultspec/rules/` from the
  filesystem and propagates to tool directories (`.claude/rules/`, etc.).
  Any rule file placed in `.vaultspec/rules/rules/` is automatically synced.
  No core code changes needed to distribute RAG-specific rules.
- **Data separation:** RAG stores Qdrant data at `.vault/data/search-data/`.
  Core's scanner globs `*.md` so Qdrant binary files are invisible. However,
  `.vault/data/` is not in core's recommended gitignore, and any stray `.md`
  in `data/` would be scanned.
- **Extension model:** core has no plugin system. Providers are hardcoded.
  RAG cannot register as a "provider" without forking core. The relationship
  is peer-to-peer, not parent-child.

## Constraints

- **No core code changes in this PR.** Core is a separate repo; changes there
  require a separate PR. All fixes must be achievable from the RAG side.
- **Backward compatibility.** Existing workspaces with only core installed
  must not break. RAG's artifacts must be additive.
- **Sync must be idempotent.** RAG's install must be safe to run repeatedly.

## Implementation

Four phases, all executable from vaultspec-rag:

**Phase 1 — Rule integration (RAG-side)**

- Create `.vaultspec/rules/rules/vaultspec-rag.builtin.md` that teaches LLMs:
  "use `vaultspec-rag search` for semantic vault/codebase search; use
  `vaultspec-core vault` for structured CRUD and health checks; use
  `vaultspec-search-mcp` MCP tools for programmatic search."
- Document RAG CLI commands, MCP tools, and when each is appropriate.
- After `vaultspec-core sync`, this rule is distributed to all configured
  provider directories and enrolled in their configs automatically.

**Phase 2 — Install command (RAG-side)**

- Add `vaultspec-rag install` subcommand to `cli.py` that:
  1. Validates a vaultspec workspace exists (`.vault/` + `.vaultspec/`).
  1. Registers `vaultspec-search-mcp` in `.mcp.json` using the same
     idempotent merge pattern as core's `_scaffold_mcp_json()`.
  1. Ensures `.vault/data/` is in `.gitignore`.
  1. Seeds `vaultspec-rag.builtin.md` into `.vaultspec/rules/rules/`.
  1. Prints a reminder to run `vaultspec-core sync` to propagate.
- Add matching `vaultspec-rag uninstall` that reverses steps 2-4. Uninstall
  must handle user-modified `.mcp.json` gracefully — only remove the
  `vaultspec-search-mcp` key if it matches the expected shape, never
  clobber user edits to other entries.

**Phase 3 — Defensive hardening (RAG-side)**

- Add `.vault/data/` to RAG's gitignore management (ensure it exists even
  if core doesn't provide it).
- Retain `VAULTSPEC_RAG_ROOT` env var — it is part of RAG's public contract
  (documented in `mcp_server.py` and referenced by external tooling).
- Document the data directory contract in the builtin rule.

**Phase 4 — Documentation**

- Document the "companion package" model in both CLIs' `--help` text.
- Add a section to the builtin rule explaining the relationship.

## Rationale

**Why "companion" not "extension":** core has no plugin system, and RAG is
not subordinate to core. Both operate on the same workspace with different
capabilities. The companion model requires no core changes — RAG seeds a
rule into `.vaultspec/rules/` and core's existing sync distributes it.

**Why seed via filesystem, not a provider registration:** core's sync reads
`.vaultspec/rules/` from disk. Placing a file there is the simplest,
most stable integration point. No enum patching, no monkey-patching, no
API changes. Works with any core version that supports sync.

**Why `.mcp.json` registration matters:** without it, LLMs using Claude Code
or other MCP-aware tools cannot discover RAG's search capabilities. The
install command bridges this gap.

**Why phase ordering:** rule integration (phase 1) delivers the highest
value — LLM awareness — with zero code changes. Install command (phase 2)
automates setup. Hardening (phase 3) and docs (phase 4) are polish.

## Consequences

- **Positive:** LLMs gain explicit guidance on RAG vs core tool selection.
  Setup becomes a single `vaultspec-rag install` command. Data directory is
  properly defended.
- **Coupling risk:** the builtin rule references specific RAG CLI commands
  and MCP tool names. If RAG's API changes, the rule must be updated.
  Mitigated by versioning the rule content alongside RAG releases.
- **Core dependency:** RAG's install assumes core's sync pipeline exists.
  If core changes its sync mechanism, RAG's seeded rule may stop propagating.
  Mitigated by the rule being a plain `.md` file — worst case, it stays in
  `.vaultspec/rules/` and users manually copy it.
- **No core-side changes:** `.vault/data/` is not added to core's scanner
  skip list or recommended gitignore in this PR. That's a separate core PR
  (recommended but not blocking).
- **Concurrency risk:** if `vaultspec-rag install` runs while
  `vaultspec-core sync` is mid-execution, file I/O races could corrupt
  `.mcp.json` or `.vaultspec/rules/`. Mitigated by using atomic writes
  (write-to-tmp + `os.replace`) for all file operations in the install
  command, consistent with existing RAG patterns (Task #43).

## Scope revision (2026-04-11)

**Status:** phases 2-4 deferred. Only phase 1 + gitattributes (#47)
proceed in this PR.

Core#36 (hook scaffolding) and core#43 (MCP registry) remain open.
Building the install/uninstall CLI, pre-commit standardization, and MCP
enrollment against APIs that are still being designed would produce
throwaway code. The ADR's phased approach anticipated this — phase 1
(rule integration) was designed to deliver value independently.

**This PR delivers:**

- Phase 1 in full: `vaultspec-rag.builtin.md` rule, `CLAUDE.md`
  enrollment, sync verification
- `.gitattributes` eol=lf normalization (#47)

**Deferred to follow-up PRs:**

- Phase 2 (install/uninstall CLI) — awaits core#43 for MCP registration
  API and core#36 for hook scaffolding pattern
- Phase 3 (defensive hardening) — depends on phase 2 infrastructure
- Phase 4 (documentation) — depends on phase 2 completion
- #48 (pre-commit hooks) — awaits core#36
- #55 (MCP registry) — awaits core#43
