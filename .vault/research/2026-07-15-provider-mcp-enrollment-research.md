---
tags:
  - '#research'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
related: []
---

# `provider-mcp-enrollment` research: `provider-native RAG MCP enrollment`

This research grounds RAG's companion MCP lifecycle against the current Codex and
Claude Code project configuration contracts, Core's provider boundary, and RAG's
tool, dependency, and dev installation modes.

## Findings

### Provider and scope contract

Claude Code 2.1.210 consumes project-scoped MCP servers from `.mcp.json` and reports
them as `Project config (shared via .mcp.json)`. Codex 0.144.4 consumes project-scoped
servers from `[mcp_servers.<name>]` tables in `.codex/config.toml`; its real
`mcp list --json` and `mcp get vaultspec-rag --json` commands recognize that surface.
Neither host's user-global configuration belongs in RAG's default lifecycle.

The Codex entry already committed in this repository is not proof of current Core
support: `git blame .codex/config.toml:1-15` attributes it to commit `d8abde28`, while
Core 0.1.43 still implements JSON-shaped targets and JSON-only status in
`vaultspec_core/core/mcps.py:354-479,778-899`. A healthy Claude target therefore
currently makes status green even when Codex is absent or drifted.

### Preserve the companion boundary

The accepted companion architecture makes Core the only writer of provider
configuration. RAG already ships one mode-neutral definition at
`src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json:1-6`, seeds it, records its
package mode, and delegates propagation. The fixed release must consume Core's public
`McpScope`, `McpTarget`, `mcp_sync`, `mcp_status`, and `mcp_uninstall` contracts. It
must not add JSON or TOML renderers, a second ownership registry, or a second drift
comparator in RAG.

Core must project the canonical definition to Claude project JSON and Codex project
TOML, preserve unrelated host configuration, migrate legacy `_vaultspecManaged`
ownership, and reconcile only explicitly owned entries. Same-name unowned entries are
collisions, not permission to adopt them. Provider-aware health is green only when
every selected project target is synchronized.

### Installation-mode matrix

| Mode         | Project dependency action for `--mcp`             | Launch                                                         |
| :----------- | :------------------------------------------------ | :------------------------------------------------------------- |
| `tool`       | No project mutation                               | `uvx --from vaultspec-rag[mcp] python -m vaultspec_rag.server` |
| `dependency` | Add `[mcp]` to the existing runtime requirement   | `uv run python -m vaultspec_rag.server`                        |
| `dev`        | Add `[mcp]` to the existing dev-group requirement | `uv run python -m vaultspec_rag.server`                        |

`_run_uv_add_mcp_extra` currently runs unconditional
`uv add vaultspec-rag[mcp]` (`src/vaultspec_rag/commands/_uv_sync.py:20-64`). That
mutates a tool-mode project and can duplicate or move a dev-only dependency into
published runtime dependencies. The current mode tests opt out of this subprocess and
therefore do not cover placement (`src/vaultspec_rag/tests/test_install_mode.py:110-119`).

Core's tool renderer must keep package identity `vaultspec-rag` for persisted mode
lookup while accepting a distinct tool distribution spec `vaultspec-rag[mcp]` for
`uvx --from`. Using the extra-bearing string as package identity would break mode
resolution; using `uvx --with mcp` would bypass RAG's own dependency contract.

### Enrollment control, preview, and migration

The CLI describes `--no-mcp` as a CLI-only workspace, but install currently seeds and
syncs the MCP definition regardless and suppresses only `uv add`. `--no-mcp` must retain
the rule and discovery skill, omit or remove the RAG MCP source, ask Core to prune owned
Claude and Codex projections, and leave unowned same-name entries untouched.

Install and uninstall dry-runs currently skip Core entirely in
`src/vaultspec_rag/commands/_install.py:74-105` and
`src/vaultspec_rag/commands/_uninstall.py:154-179`. The fixed commands must invoke
Core's real dry-run so structured reports describe per-provider additions, drift
repairs, and removals without changing bytes or provisioning dependencies.

Mode transitions reconcile dependency placement and both provider targets together.
RAG has no durable ownership record for legacy dependency-extra changes, so it must not
automatically remove a suspected historical runtime dependency. New managed changes
need enough durable placement provenance for uninstall to remove only the `[mcp]`
addition while retaining the base dependency. A second identical install or upgrade
must be byte-stable and avoid needless dependency resolution.

### Alternatives rejected

- RAG-owned JSON/TOML writers duplicate Core's provider, ownership, and drift logic.
- Global registration uses the wrong scope and is not portable across hosts.
- `.mcp.json` alone proves Claude enrollment, not Codex enrollment.
- Unconditional `uv add vaultspec-rag[mcp]` violates tool and dev placement.
- Automatic adoption of same-name host entries destroys user ownership.
- Separate per-provider RAG definitions create launch drift.

### Release gate

RAG 0.3.0 currently declares `vaultspec-core>=0.1.39`; the project lock resolves Core
0.1.41 and the installed CLI is 0.1.43. The RAG release must wait for the first
published Core version carrying the typed provider contracts and extra-aware tool
renderer, raise its floor to that exact version, and resolve against the published
artifact.

Acceptance must cover Claude-only, Codex-only, and dual-provider project enrollment;
all three installation modes; `--no-mcp` transition; legacy managed JSON and unowned
TOML collisions; provider-local drift and repair; byte-identical reinstall; real
dry-run; ownership-safe uninstall; and real `claude mcp get vaultspec-rag` plus
`codex mcp get vaultspec-rag --json`. The semantic index was unavailable for the new
worktree, so discovery used the mandated exact-source fallback.
