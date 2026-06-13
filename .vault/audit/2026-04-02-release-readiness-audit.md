---
title: release-readiness-audit
date: 2026-04-02
modified: '2026-04-02'
tags:
  - '#audit'
  - '#release-readiness'
related:
  - '[[2026-04-01-cicl-pipeline-adr]]'
---

# release-readiness audit — alpha → beta gap analysis

Cross-repo convention audit comparing **vaultspec-rag** (0.1.1) against
**vaultspec-core** (0.1.19) to identify gaps blocking beta readiness.

Audit scope: CLI conventions, Justfile, MCP discoverability, dependency
management, documentation, pre-commit hooks, CI/CD, pyproject.toml metadata,
and framework integration.

______________________________________________________________________

## CRITICAL gaps (must fix before beta)

### C1 — No Justfile

**Core** has a full `justfile` with structured dev workflow:

- `just prod [args]` — mirror of CLI
- `just dev {deps|lint|fix|audit|test|build|publish|precommit}` — dev meta-recipe
- `just ci` — full CI pipeline
- Internal recipes: `_dev-deps`, `_dev-lint`, `_dev-fix`, `_dev-audit`,
  `_dev-test`, `_dev-build`, `_dev-publish`, `_dev-precommit`

**RAG** has no task runner at all. A developer familiar with vaultspec-core
would expect `just dev test`, `just dev lint`, `just ci` to work identically.

**Action:** Create `justfile` mirroring core's recipe naming and structure,
adapted for RAG-specific commands (GPU tests, model downloads, etc.).

### C2 — MCP server not self-registering in .mcp.json

**Core** scaffolds `.mcp.json` during `vaultspec-core install` via
`_scaffold_mcp_json()`. The RAG MCP server (`vaultspec-search-mcp`) has no
equivalent registration mechanism.

Current `.mcp.json` in RAG repo only contains `vaultspec-core`. A developer
or IDE has no way to discover the RAG MCP server without manual configuration.

**Action:** Implement a `vaultspec-rag install` (or `vaultspec-rag setup`)
command that merges `vaultspec-search-mcp` into `.mcp.json` using the same
merge-without-overwrite pattern as core. Entry should be:

```json
{
  "vaultspec-search-mcp": {
    "command": "uv",
    "args": ["run", "python", "-m", "vaultspec_rag.mcp_server"]
  }
}
```

### C3 — Documentation is absent

**Core** has:

- `README.md` — installation, getting started, development workflow
- `.vaultspec/README.md` — framework manual
- `.vaultspec/CLI.md` — complete command reference with tables
- `.vaultspec/MCP.md` — server setup, tools, parameters, response formats

**RAG** has:

- `README.md` — 23 lines, feature bullet list, minimal dev setup
- No CLI reference
- No MCP server documentation
- No `.vaultspec/` documentation files

**Action:** Write from scratch:

- `README.md` — full project overview, prerequisites (GPU, HF_TOKEN),
  installation, quickstart, development workflow
- `.vaultspec/CLI.md` — all commands/subcommands with options tables
- `.vaultspec/MCP.md` — 7 tools, 1 resource, 1 prompt, parameters, responses

### C4 — vaultspec-cli.builtin.md documents wrong CLI

`.claude/rules/vaultspec-cli.builtin.md` and
`.vaultspec/rules/rules/vaultspec-cli.builtin.md` describe **vaultspec-core**
commands (`vault add`, `spec rules list`, `install`, `sync`). They should
document **vaultspec-rag** commands (`index`, `search`, `status`, `server`,
etc.) or include both CLIs.

This actively misleads the AI agent about available commands in this repo.

**Action:** Rewrite to document vaultspec-rag CLI commands. If vaultspec-core
commands are also needed (since it's a dependency), add a separate section or
a second rule file.

______________________________________________________________________

## HIGH gaps (should fix before beta)

### H1 — pyproject.toml metadata incomplete

**Core** has: classifiers (8), keywords (6), URLs (4: Homepage, Repository,
Documentation, Bug Tracker).

**RAG** has: none of these.

**Action:** Add matching metadata:

```toml
[project]
keywords = ["rag", "mcp", "vaultspec", "embeddings", "gpu", "vector-search"]

[project.urls]
Homepage = "https://github.com/wgergely/vaultspec-rag"
Repository = "https://github.com/wgergely/vaultspec-rag"
Documentation = "https://github.com/wgergely/vaultspec-rag/tree/main/.vaultspec/README.md"
"Bug Tracker" = "https://github.com/wgergely/vaultspec-rag/issues"

classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Text Processing :: Indexing",
    "Typing :: Typed",
]
```

### H2 — Pre-commit hooks diverge from core convention

**Core** uses read-only gate hooks (no auto-fix):

- `ruff check` (no `--fix`)
- `ruff format --check` (no formatting)
- `taplo lint` (no `fmt`)
- 3x `vault check` hooks (structure, dangling, body-links)
- `mdformat-check`
- `pymarkdown`

**RAG** uses auto-fixing hooks:

- `ruff check --fix` (mutates files)
- `ruff format` (mutates files)
- `taplo-format` + `taplo-lint` (format mutates)
- No vault check hooks
- `markdownlint` (different tool than core's mdformat + pymarkdown)

**Actions:**

- Switch to read-only gates matching core: `ruff check` (no --fix),
  `ruff format --check`, `taplo lint` (no fmt)
- Add vault check hooks: `check-naming`, `check-dangling`, `check-body-links`
  (requires vaultspec-core to be installed)
- Align markdown linting: switch to `mdformat-check` + `pymarkdown` or
  justify the divergence
- Move auto-fix to `just dev fix` recipes (matching core pattern)

### H3 — CI missing vault-audit job

**Core** CI has a dedicated `vault-audit` job:
`vaultspec-core vault check all`

**RAG** CI has no vault health check. The `.vault/` documents could
accumulate broken links, naming violations, or frontmatter errors undetected.

**Action:** Add `vault-audit` job to `.github/workflows/ci.yml`.

### H4 — No `vaultspec-rag sync` command

**Core** has `sync [provider]` which propagates rules/skills/agents/system
to provider directories. RAG has no equivalent.

When vaultspec-core syncs to a project, the RAG MCP server, its skills,
and its rules are invisible. There's no mechanism for RAG to contribute:

- A custom skill (e.g., `vaultspec-rag/SKILL.md`) for AI tool discovery
- A custom rule for when/how to use RAG search
- A system prompt fragment describing RAG capabilities

**Action:** Implement either:

- (a) A `vaultspec-rag sync` command that writes skill/rule files into
  `.vaultspec/rules/` for core to pick up on next sync, or
- (b) Ship a bundled skill definition that core's install/sync can discover
  (e.g., via a well-known package entry point or `.vaultspec/` convention)

This is the "discoverability" feature the user flagged.

### H5 — Graph rebuild race (R36-C1) still open

From round 36 audit: `search.py:_get_graph()` has no lock around VaultGraph
rebuild. Concurrent searches at TTL boundary trigger parallel graph
constructions. Needs `threading.Lock` with double-check pattern.

**Action:** Fix before beta. This is a correctness issue under load.

______________________________________________________________________

## MEDIUM gaps (should address for beta)

### M1 — CLI entry point naming convention

**Core:** `vaultspec-core` → `vaultspec_core.__main__:main`
**Core MCP:** `vaultspec-mcp` → `vaultspec_core.mcp_server.app:run`

**RAG:** `vaultspec-rag` → `vaultspec_rag.cli:app`
**RAG MCP:** `vaultspec-search-mcp` → `vaultspec_rag.mcp_server:main`

The MCP entry point naming diverges: core uses `vaultspec-mcp`, RAG uses
`vaultspec-search-mcp`. For ecosystem consistency, consider renaming to
`vaultspec-rag-mcp` (matching the `vaultspec-{module}-mcp` pattern, though
core doesn't use this pattern either).

Also: core routes through `__main__:main`, RAG goes directly to `cli:app`.
Minor, but adding a `__main__.py` with `from vaultspec_rag.cli import app; app()`
would allow `python -m vaultspec_rag` invocation (which core supports).

### M2 — Missing `doctor` command

**Core** has `vaultspec-core doctor` for workspace health diagnosis.

**RAG** has `vaultspec-rag status` which shows GPU/index info but doesn't
diagnose problems (missing models, broken Qdrant DB, stale indexes,
HF_TOKEN not set, CUDA unavailable).

**Action:** Add a `doctor` command or extend `status` to include diagnostic
checks with actionable remediation hints.

### M3 — No `uninstall` command

**Core** has `vaultspec-core uninstall` to clean up deployed files.

**RAG** has no cleanup mechanism. If the MCP entry gets added to `.mcp.json`
(per C2), there should be a way to remove it.

### M4 — `uv run --no-sync` not used in pre-commit

**Core** pre-commit entries use `uv run --no-sync` to avoid unnecessary
lock resolution during hook runs.

**RAG** uses bare `ruff` or `uv run python` without `--no-sync`.

### M5 — Missing `--json` output flag convention

**Core** commands consistently offer `--json` for machine-readable output
(used by CI, scripts, other tools).

**RAG** commands output Rich-formatted text only. The `status`, `search`,
and `index` commands should support `--json` for programmatic consumption.

### M6 — Test marker alignment

**Core** markers: `unit`, `integration`, `api`, `gemini`, `claude`, `e2e`,
`timeout`.

**RAG** markers: `unit`, `integration`, `performance`, `quality`,
`robustness`, `timeout`.

The `performance`, `quality`, `robustness` markers are RAG-specific and
appropriate. But RAG is missing an `api` marker for testing the public
facade (`api.py`). Consider adding for consistency.

______________________________________________________________________

## LOW gaps (nice to have)

### L1 — No `.vaultspec/README.md` framework manual

Core ships a framework manual at `.vaultspec/README.md`. RAG has no
equivalent. For a developer onboarding to the RAG module, a manual
explaining the GPU requirements, model architecture, indexing pipeline,
and search semantics would be valuable.

### L2 — Markdown linting tool mismatch

Core uses `mdformat` + `pymarkdown`. RAG uses `markdownlint-cli` (Node.js).
Both achieve the same goal but with different rulesets. For strict
convention alignment, RAG should switch to mdformat + pymarkdown and add
them to dev dependencies.

### L3 — No Docker support

Core has Docker build/publish recipes and CI workflows. RAG has none.
For deployment scenarios (especially GPU containers), a Dockerfile and
`just dev build docker` recipe would be valuable.

### L4 — Hook definitions

Core has `.vaultspec/rules/hooks/example-audit-on-create.yaml`. RAG has
the same example hook but no RAG-specific hooks. Consider:

- `rag-reindex-on-vault-create.yaml` — auto-reindex when vault docs added
- This would integrate with the existing `watcher.py` functionality

### L5 — System prompt files

Core has 4 system prompt files in `.vaultspec/rules/system/`
(`01-core.md`, `02-operations.md`, `03-vaultspec.md`, `90-custom.md`).

RAG has the same files (synced from core). No RAG-specific system prompt
additions. Consider adding a `50-rag.md` that describes RAG search
capabilities to AI agents.

______________________________________________________________________

## Summary matrix

| Area                         |         Core         |     RAG      |   Gap    |
| :--------------------------- | :------------------: | :----------: | :------: |
| Justfile                     |       ✅ Full        |   ❌ None    | CRITICAL |
| MCP .mcp.json registration   |       ✅ Auto        |  ❌ Manual   | CRITICAL |
| Documentation (README)       |       ✅ Full        |  ❌ Minimal  | CRITICAL |
| Documentation (CLI.md)       |     ✅ Complete      |   ❌ None    | CRITICAL |
| Documentation (MCP.md)       |     ✅ Complete      |   ❌ None    | CRITICAL |
| CLI rule accuracy            |      ✅ Correct      | ❌ Wrong CLI | CRITICAL |
| pyproject.toml metadata      |     ✅ Complete      |  ❌ Missing  |   HIGH   |
| Pre-commit (read-only gates) |       ✅ Gates       | ⚠️ Auto-fix  |   HIGH   |
| Pre-commit (vault checks)    |      ✅ 3 hooks      |   ❌ None    |   HIGH   |
| CI vault-audit job           |      ✅ Present      |  ❌ Missing  |   HIGH   |
| Sync/discoverability         |   ✅ install+sync    |   ❌ None    |   HIGH   |
| Graph rebuild race           |         n/a          |   ❌ Open    |   HIGH   |
| Entry point naming           |    ✅ Consistent     | ⚠️ Diverges  |  MEDIUM  |
| Doctor command               |      ✅ Present      |  ❌ Missing  |  MEDIUM  |
| Uninstall command            |      ✅ Present      |  ❌ Missing  |  MEDIUM  |
| --json output                |     ✅ All cmds      |   ❌ None    |  MEDIUM  |
| **main**.py                  |      ✅ Present      |  ❌ Missing  |  MEDIUM  |
| Framework manual             | ✅ .vaultspec/README |   ❌ None    |   LOW    |
| Docker support               |       ✅ Full        |   ❌ None    |   LOW    |
| RAG-specific hooks           |         n/a          |   ❌ None    |   LOW    |
| RAG system prompt            |         n/a          |   ❌ None    |   LOW    |

______________________________________________________________________

## Recommended work issue order

**Phase 1 — Convention alignment (blocking beta):**

- Issue: Create justfile matching core conventions
- Issue: Add `vaultspec-rag install` / `setup` command (MCP registration)
- Issue: Rewrite vaultspec-cli.builtin.md for RAG CLI
- Issue: Write README.md, .vaultspec/CLI.md, .vaultspec/MCP.md
- Issue: Add pyproject.toml metadata (classifiers, keywords, URLs)

**Phase 2 — Quality gates (blocking beta):**

- Issue: Align pre-commit hooks to read-only gates
- Issue: Add vault check hooks to pre-commit
- Issue: Add vault-audit job to CI
- Issue: Fix R36-C1 graph rebuild race

**Phase 3 — Developer experience (beta polish):**

- Issue: Add `doctor` command
- Issue: Add `--json` output to CLI commands
- Issue: Add `__main__.py` for `python -m vaultspec_rag`
- Issue: Rename `vaultspec-search-mcp` → `vaultspec-rag-mcp`
- Issue: Add `uninstall` command
- Issue: Implement sync/discoverability (skill + rule + system prompt)

**Phase 4 — Ecosystem integration (post-beta):**

- Issue: Write .vaultspec/README.md framework manual
- Issue: Add RAG-specific system prompt (50-rag.md)
- Issue: Add RAG-specific hooks (reindex on vault create)
- Issue: Docker support
- Issue: Align markdown linting tools (mdformat + pymarkdown)
