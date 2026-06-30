---
tags:
  - '#adr'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-mcp-optional-dependency-research]]"
---

# `mcp-optional-dependency` adr: `Make mcp an optional extra; the CLI and daemon do not depend on it` | (**status:** `accepted`)

## Problem Statement

`mcp` is a hard core dependency of a CLI-first tool whose CLI and HTTP search
daemon never import it. On Windows that core dependency transitively forces
`pywin32`, whose post-install step routinely fails under uv
(modelcontextprotocol/python-sdk#2233), breaking a plain `pip install vaultspec-rag`. Issue #184 deferred this as blocked on an upstream lazy-import
fix. The grounding research shows the blockage is self-inflicted: only the
optional stdio MCP entry point imports `mcp`, and it already guards the import.
This ADR decides to demote `mcp` to an optional extra, removing the forced
`pywin32` install from the CLI path without waiting for upstream.

## Considerations

`mcp` was promoted to a core dependency in the `2026-06-10-install-mcp-dependency-fix`
ADR because the daemon then mounted the MCP app in its lifespan and imported
`mcp` unconditionally. The later MCP service-client / conformance work removed
that mount: the daemon now serves native REST only and does not import `mcp`
(documented in `server/_main.py`). The premise of the core-dependency decision no
longer holds, so this ADR supersedes that part of it. `pywin32` itself is needed
only by `mcp.client.stdio` (a transport vaultspec-rag never uses - its MCP
surface is a FastMCP HTTP server), so it is doubly unnecessary on the search
path.

## Considered options

- **Wait for upstream (status quo / #184):** keep `mcp` core, wait for the
  lazy-import fix. Rejected: passive, leaves CLI installs broken on Windows
  indefinitely for a dependency the CLI does not use.
- **Demote `mcp` to an optional `[mcp]` extra (chosen):** the CLI and daemon do
  not declare or import it; only `vaultspec-rag[mcp]` (the MCP server) pulls it.
- **Shim/patch `pywin32` at import time:** rejected - the failure is at *install*
  time (wheel/post-install), before any import, so an import-time shim cannot
  help.
- **Soft-fail the eager `mcp` import inside the package:** unnecessary - the only
  importer (`server/_main.py`) already guards it.

## Constraints

This supersedes the core-`mcp` decision of `2026-06-10-install-mcp-dependency-fix`
and must keep that ADR's guard rail (the `try/except ImportError` with an
actionable message) intact, retargeted to point at the extra. It must not move
any `mcp` import onto the CLI or daemon path (verified absent today). The project's
own tests import `mcp`, so the dev/test dependency set must continue to provide it.
The `vaultspec-search-mcp` console entry point and any MCP launcher config now
require `vaultspec-rag[mcp]`; the install documentation and the guard message must
say so. The `[mcp]` extra already exists as a deprecated no-op alias, so the
spelling stays stable for users.

## Implementation

- **MO1 - `mcp` moves from core to the `[mcp]` extra.** Remove `mcp>=1.26.0`
  from `[project.dependencies]` and define `[project.optional-dependencies].mcp = ["mcp>=1.26.0"]`, replacing the no-op alias. A bare `pip install vaultspec-rag`
  then installs no `mcp` and no `pywin32`; `pip install vaultspec-rag[mcp]`
  installs the MCP server's dependency.

- **MO2 - The dev/test environment carries the extra.** The development
  dependency set includes `mcp` (directly or via the `[mcp]` extra) so the test
  suite, which imports `mcp`, continues to resolve.

- **MO3 - The guard message points at the extra.** `server/_main.py`'s
  `ImportError` guard changes its remediation from "reinstall vaultspec-rag (mcp
  is a core dependency)" to "install the MCP extra: `pip install vaultspec-rag[mcp]`" (keeping the pywin32-postinstall hint for the
  extra-present-but-broken case).

- **MO4 - A regression test pins the contract.** A test asserts that importing
  `vaultspec_rag` and the CLI app loads neither `mcp` nor any `pywin32` module,
  so a future eager import on the CLI path fails the build.

## Rationale

The dependency graph should match what the code actually uses. The CLI and daemon
do not use `mcp`, so forcing it - and its broken-on-Windows `pywin32` transitive -
on every install is a defect, not a requirement. Demoting it to an extra makes the
default install match the CLI-first product, fixes the Windows install break for
the common case, and resolves #182/#184 with a one-line dependency move plus a
message change - no upstream dependency, no shim. The guard already in place means
the only behavioral change for an MCP user is an explicit, clearly-messaged
`[mcp]` install.

## Consequences

A plain `pip install vaultspec-rag` no longer pulls `mcp`/`pywin32`; Windows CLI
installs stop hitting the pywin32 post-install break. Users who run the MCP server
(`vaultspec-search-mcp`, or an agent launcher) must install `vaultspec-rag[mcp]`,
surfaced by the install docs and the guard message. The `2026-06-10-install-mcp-dependency-fix`
ADR's core-dependency decision is superseded (its guard-rail and 3-state error
taxonomy survive). The regression test keeps the CLI path `mcp`-free. When upstream
eventually ships the lazy-import fix, no further action is needed here - the extra
is the right shape regardless.

## Codification candidates

- **Rule slug:** `cli-path-imports-no-optional-surface-deps`.
  **Rule:** Code on the always-installed CLI/daemon import path must not import a
  package that belongs to an optional extra (e.g. `mcp`); such imports stay behind
  the guarded entry point that the extra backs, so a base install never drags an
  optional surface's transitive dependencies.
