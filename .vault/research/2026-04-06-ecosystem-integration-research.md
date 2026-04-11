---
tags:
  - '#research'
  - '#ecosystem-integration'
date: 2026-04-06
related:
  - '[[2026-04-06-ecosystem-integration-adr]]'
  - '[[2026-04-06-ecosystem-integration-plan]]'
  - '[[2026-04-02-service-graph-research]]'
  - '[[2026-04-01-cicl-pipeline-research]]'
---

# `ecosystem-integration` research: `vaultspec-rag + vaultspec-core cohabitation`

Cross-repo investigation into how vaultspec-rag and vaultspec-core coexist
in the same worktree. Covers CLI compatibility, rule coverage, sync pipeline,
data separation, config alignment, install mechanics, and extension model.

## Q1: CLI compatibility

**No entry-point conflicts.** Both packages can be installed in the same venv.

| Package        | Entry points                            | Source                                                              |
| -------------- | --------------------------------------- | ------------------------------------------------------------------- |
| vaultspec-core | `vaultspec-core`, `vaultspec-mcp`       | `vaultspec_core.__main__:main`, `vaultspec_core.mcp_server.app:run` |
| vaultspec-rag  | `vaultspec-rag`, `vaultspec-search-mcp` | `vaultspec_rag.__main__:main`, `vaultspec_rag.mcp_server:main`      |

All four entry points use distinct names. No `console_scripts` collision.

Core CLI commands: `install`, `uninstall`, `sync`, `doctor`, `vault` (sub-group),
`spec` (sub-group).

RAG CLI commands: `index`, `search`, `status`, `server` (sub-group),
`benchmark`, `quality`, `test`.

No command-name overlap. Both can coexist safely.

## Q2: rule coverage (RAG awareness in core)

**Core's rule system has zero mentions of RAG.** Grep for "rag" (case-insensitive)
across all 38 files in `.vaultspec/rules/` returned no matches.

Core ships 9 skills, 9 agent personas, 4 system rules, 2 builtin rules, and
9 templates. None reference search, indexing, embeddings, or MCP-based
semantic retrieval. The single MCP mention is a generic instruction in
`vaultspec-adr-researcher.md` line 31: "Consider MCP tools, skills and cli
commands."

**Gap:** LLMs operating under vaultspec have no guidance on when to use RAG
for semantic search vs core's `vault list`/`vault check` for structured
vault management. This is the primary integration gap.

**Recommended new artifacts:**

- A `vaultspec-rag.builtin.md` rule (synced by core) that teaches: "use
  `vaultspec-rag search` for semantic search across vault and codebase; use
  `vaultspec-core vault` for structured vault CRUD and health checks."
- Optionally, a RAG-aware research skill variant that delegates to the MCP
  search tool for knowledge discovery.

## Q3: core's sync pipeline

`vaultspec-core sync` executes 5 resource passes:

1. Rules sync (`rules_sync()`)
1. Skills sync (`skills_sync()`)
1. Agents sync (`agents_sync()`)
1. System prompts sync (`system_sync()`)
1. Config files sync (`config_sync()`)

Source: `.vaultspec/rules/` (framework root). Destination: tool-specific
directories (`.claude/rules/`, `.claude/skills/`, etc.) determined by
`ToolConfig` dataclass per provider.

**Provider set is hardcoded:**
`SYNC_PROVIDERS = {"all", "claude", "gemini", "antigravity", "codex"}` in
`commands.py:1138`. No plugin discovery. No third-party provider registration.

**`_scaffold_mcp_json`** (commands.py:192-237): merges a `vaultspec-core`
server entry into `.mcp.json`. Idempotent and non-destructive (skips if key
exists, preserves user entries). RAG could use the same pattern to register
`vaultspec-search-mcp` alongside core's entry.

**Can sync discover RAG rules automatically?** No. Core reads from its own
`vaultspec_core.builtins` package. However, if RAG places a rule file
(e.g., `vaultspec-rag.builtin.md`) into `.vaultspec/rules/rules/`, core's
sync will propagate it to all tool directories because sync reads the
filesystem, not just builtins.

**Recommended approach:** RAG ships a `.vaultspec/rules/rules/vaultspec-rag.builtin.md`
that core's sync picks up and distributes. No core code changes needed.

## Q4: `.vault/data/` separation

**Qdrant storage:** `{root}/.vault/data/search-data/qdrant/` (binary protobuf
files). Index metadata stored as JSON alongside.

**Core's `vault check` does NOT scan `.vault/data/`:**

- `scan_vault()` in `scanner.py:29-55` uses `docs_dir.rglob("*.md")`
- Qdrant files are binary, not `.md` — they are invisible to the glob
- Core skips `.obsidian/` and `_archive/` explicitly but does NOT explicitly
  skip `data/`
- **Edge case:** any `.md` file accidentally placed in `.vault/data/` would
  be scanned and potentially fail validation

**Gitignore status:**

- RAG's `.gitignore` line 165: `.vault/data/search-data/` is ignored
- Core's `.gitignore`: does NOT mention `.vault/data/`
- **Risk:** if RAG is installed but its `.gitignore` entry is missing (e.g.,
  fresh clone with only core), Qdrant data could be accidentally committed

**Recommended fixes:**

- Core should add `.vault/data/` to its recommended gitignore entries
  (`get_recommended_entries()` in `core/gitignore.py`)
- Alternatively, RAG's install should ensure the gitignore entry exists
- Consider adding `data/` to scanner.py's skip list for defense-in-depth

## Q5: config alignment

**No env var conflicts.** Clean namespace separation:

| Prefix           | Package | Examples                                                                  |
| ---------------- | ------- | ------------------------------------------------------------------------- |
| `VAULTSPEC_`     | core    | `VAULTSPEC_TARGET_DIR`, `VAULTSPEC_DOCS_DIR`, `VAULTSPEC_FRAMEWORK_DIR`   |
| `VAULTSPEC_RAG_` | rag     | `VAULTSPEC_RAG_DATA_DIR`, `VAULTSPEC_RAG_PORT`, `VAULTSPEC_RAG_LOG_LEVEL` |

RAG defines `VAULTSPEC_RAG_ROOT` in its `EnvVar` enum but does not actively
use it — root resolution delegates to core's `VaultSpecConfig.target_dir`.
This is an orphaned definition that should be cleaned up or wired in.

RAG's `VaultSpecConfigWrapper` proxies to core's `VaultSpecConfig` via
`self._base`, so both packages agree on workspace root, docs dir, and
framework dir. Config resolution order for RAG keys: CLI override >
env var > `_RAG_DEFAULTS`.

**No conflict. Integration is clean.**

## Q6: install/uninstall

**RAG has no `install` command.** It relies on:

1. Python package installation (`uv pip install vaultspec-rag`)
1. Pre-existing vaultspec workspace (`.vault/` and `.vaultspec/` must exist)
1. Workspace validation via `resolve_workspace()` in `workspace.py`

**Core provides rich install infrastructure** that RAG could leverage:

- `_scaffold_mcp_json()` — register RAG's MCP server in `.mcp.json`
- `ensure_gitignore_block()` — add `.vault/data/` to `.gitignore`
- `seed_builtins()` — could be extended to seed RAG-specific rules
- Manifest management — track RAG as an installed component
- Diagnosis/resolution — detect and fix RAG integration issues

**Recommended approach:** RAG should implement a minimal `install` command that:

1. Validates workspace exists (or delegates to `vaultspec-core install`)
1. Registers `vaultspec-search-mcp` in `.mcp.json` (using same pattern as
   `_scaffold_mcp_json`)
1. Ensures `.vault/data/` is in `.gitignore`
1. Seeds `vaultspec-rag.builtin.md` into `.vaultspec/rules/rules/`
1. Triggers `vaultspec-core sync` to propagate the new rule

## Q7: extension model

**Core has no formal extension/plugin system.** Providers are hardcoded in a
`Tool` enum and `_PROVIDER_TO_TOOLS` mapping. No dynamic registration, no
plugin discovery, no entry-point scanning.

**vaultspec-rag is best described as a "companion package"** — it:

- Shares the same workspace (`.vault/`, `.vaultspec/`)
- Delegates config resolution to core's `VaultSpecConfig`
- Operates on the same document corpus but with different tools (embeddings,
  vector search vs structured CRUD)
- Has its own CLI, MCP server, and data directory

**Neither "extension" nor "plugin" accurately describes the relationship.**
The term "companion" is more accurate: two cooperating packages that share a
workspace without one being subordinate to the other.

## Findings summary

| Area             | Status                                              | Action needed                                           |
| ---------------- | --------------------------------------------------- | ------------------------------------------------------- |
| CLI entry points | No conflict                                         | None                                                    |
| Rule coverage    | **GAP** — core has zero RAG awareness               | Ship `vaultspec-rag.builtin.md` rule                    |
| Sync pipeline    | Works for RAG if rule placed in `.vaultspec/rules/` | RAG install should seed the rule                        |
| `.vault/data/`   | Separated but fragile                               | Add to core's gitignore; consider scanner skip          |
| Config/env vars  | Clean separation                                    | Remove orphaned `VAULTSPEC_RAG_ROOT`                    |
| Install command  | **MISSING** in RAG                                  | Implement minimal install (mcp.json + gitignore + rule) |
| Extension model  | None in core                                        | Document "companion" relationship                       |

## Recommended implementation order

- **Phase 1 (rule integration):** Create `vaultspec-rag.builtin.md`, seed
  it during RAG install, let core sync propagate it
- **Phase 2 (install command):** Implement `vaultspec-rag install` that
  registers MCP server, ensures gitignore, seeds rule
- **Phase 3 (defensive hardening):** Add `.vault/data/` to scanner skip
  list in core; clean up orphaned `VAULTSPEC_RAG_ROOT`
- **Phase 4 (documentation):** Document companion model in both repos

## Scope revision (2026-04-11)

Review of upstream dependencies revealed that core#36 (pre-commit hook
standardization) and core#43 (MCP server registry) are still open and
in progress. The install/uninstall CLI commands (#54 phase 2), pre-commit
hook standardization (#48), and MCP registry enrollment (#55) all depend
on core APIs that have not yet landed.

**Revised scope for this PR:** only items with zero core dependencies:

- **#54 (partial):** rule authoring + CLAUDE.md enrollment + sync
  verification. The install CLI command is deferred until core's
  extension points stabilize.
- **#47:** `.gitattributes` eol=lf completion + `git add --renormalize .`

**Deferred to follow-up PRs (blocked on core):**

- **#48:** pre-commit hook standardization — awaits core#36
- **#55:** MCP server registry enrollment — awaits core#43
- **#54 (install/uninstall commands):** deferred until core's MCP registry
  and hook scaffolding land, so the install command can use official APIs
  rather than hand-rolling `.mcp.json` manipulation that will be
  immediately replaced
