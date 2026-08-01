---
tags:
  - '#research'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-27'
body_hash: 'sha256:932a4ca4f64d93e818d5a27347f48e290466168e46b54b4d9083b89490365c85'
related: []
---

# `mcp-launch-hygiene` research: `binding rag to core's static-launch MCP contract`

Grounding for rag's half of the launch-hygiene contract that core amended in
its PR 224 / `2026-07-17-mcp-static-launch-adr` (every rendered MCP launch is
a side-effect-free static execution; a connect-time implicit `uv sync`
corrupted a workspace venv on 2026-07-17). Upstream report: this repo's
issue 231, filed by the core team.

## Findings

### R1 - Tool-mode render is silently broken without a tool-spec token

`src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json` carries
`_vaultspec_mode_package` and `_vaultspec_mode_module` but no
`_vaultspec_mode_tool_spec`. Because `mcp` is an optional extra
(mcp-optional-dependency ADR), a tool-mode render becomes
`uvx --from vaultspec-rag python -m vaultspec_rag.server` - an environment
without the `mcp` dependency, guaranteed `ImportError`. Core's renderer
consumes and strips `_vaultspec_mode_tool_spec` for exactly this case.
Dependency/dev workspaces mask the defect because their dev environment
installs the extra.

Source: issue 231 item 1; the builtin seed file; core renderer contract.

### R2 - The upgrade path already force-refreshes stale seeds; unproven by tests

`seed_builtins` skips existing files unless forced, and the installer calls
it with `force=force or upgrade` (`commands/_install.py`), so
`vaultspec-rag install --upgrade` rewrites a pre-parity exe-form
`mcps/vaultspec-rag.builtin.json` to the tokenized form ([UPDATE] action on
content difference). Correct in code, but no regression test pins the
stale-seed-refresh path, and the remediation is undocumented for operators
holding pre-parity workspaces (the Windows exe-lock incident shape).

Source: `src/vaultspec_rag/builtins/__init__.py` seed loop;
`commands/_install.py` `_seed_builtins`; issue 231 item 2.

### R3 - The mcp-extra step ignores the declared placement

`_run_uv_add_mcp_extra` (`commands/_uv_sync.py`) shells out to a bare
`uv add vaultspec-rag[mcp]`, which always targets the host's runtime
`[project.dependencies]`. In dev mode - where rag lives in a PEP 735 dev
group - this leaks a runtime, published dependency into the host project
(observed on the core main worktree under 0.3.0, hand-reverted). The
installer already resolves the mode before this step runs, and `uv add --group <name>` updates an existing group entry in place.

Source: `commands/_uv_sync.py`; `commands/_install.py` mode resolution;
issue 231 item 3.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
