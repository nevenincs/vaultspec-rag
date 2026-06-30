---
tags:
  - '#research'
  - '#mcp-optional-dependency'
date: '2026-06-30'
modified: '2026-06-30'
related: []
---

# `mcp-optional-dependency` research: `Demote mcp to an optional extra so CLI installs do not drag pywin32`

`vaultspec-rag` is a CLI-first tool whose default value - GPU hybrid search via
the `vaultspec-rag` command and the supervised HTTP search daemon - does not use
the `mcp` package at all. Yet `mcp` is a hard core dependency, and on Windows it
transitively forces `pywin32`, whose post-install step routinely fails under uv
(modelcontextprotocol/python-sdk#2233), breaking plain CLI installs. Issue #184
deferred this as "blocked until upstream ships a lazy-import fix." This research
shows the blockage is avoidable on our side: nothing on the CLI/daemon path needs
`mcp`, so demoting it to an optional extra removes the forced `pywin32` install
without waiting for upstream.

## Findings

### 1. Neither the CLI nor the HTTP daemon imports `mcp`

Measured directly: `import vaultspec_rag`, and importing the CLI app
(`vaultspec_rag.cli.app`), pull in neither `mcp` nor any `pywin32` module
(`win32*`/`pywintypes`/`pythoncom` absent from `sys.modules`). The HTTP search
daemon is explicit about it: `server/_main.py` documents that "the HTTP daemon no
longer mounts any MCP app, so it never needs the package," and imports `mcp` only
inside the `else` branch that starts the **stdio MCP transport** - guarded by a
`try/except ImportError`. So `mcp` is reachable from exactly one optional entry
point, not from the search path the CLI and its daemon exercise.

### 2. `pywin32` is a transitive dep of a transport vaultspec-rag never uses

`mcp`'s `__init__.py` eagerly imports `client.stdio`, which pulls `pywin32`
(Windows Job Objects for managing **stdio-client** child processes). But
vaultspec-rag's MCP surface is a FastMCP **server** on the Streamable HTTP
transport (`mcp/_mcp.py`, `stateless_http=True`); it never instantiates the stdio
*client*. So `pywin32` is doubly unnecessary: needed only by a transport
(`client.stdio`) that vaultspec-rag does not use, reached only through an
optional entry point. The CLI "does not need it" because it never touches `mcp`;
the MCP surface "needs it" only because `mcp`'s eager import drags it, not because
any vaultspec-rag code calls it.

### 3. The core-dependency rationale is now obsolete

`mcp` was promoted from an extra to a core dependency in #182 because, at the
time, "the server imports it unconditionally" - the daemon mounted the MCP app in
its lifespan. The later MCP service-client / conformance work decoupled that: the
daemon now serves native REST only and does not import `mcp`. The condition that
justified the core dependency no longer holds, so the promotion can be reversed.
The `[mcp]` extra still exists as a deprecated no-op alias (`mcp = []`), so the
spelling `vaultspec-rag[mcp]` already resolves - it just needs to carry the real
dependency again.

### 4. The guard rail is already in place

`server/_main.py` already wraps `from ..mcp import mcp` in `try/except ImportError` with an actionable message. Once `mcp` is an extra, that message is
the single place that tells a user who runs the MCP entry point without the extra
to install `vaultspec-rag[mcp]`. No other code path needs a guard, because no
other code path imports `mcp`.

### 5. Fix space and risks

The fix is to move `mcp>=1.26.0` from `[project.dependencies]` into
`[project.optional-dependencies].mcp`, and update the guard message from "mcp is
a core dependency" to "install `vaultspec-rag[mcp]`". Risks to weigh in the ADR:
(a) the `vaultspec-search-mcp` console entry point and any MCP launcher config
now require the `[mcp]` extra - the install story must make that explicit; (b)
the project's own dev/test environment imports `mcp` in tests, so the dev extra
(or the test path) must include it; (c) a user who previously relied on a bare
`pip install vaultspec-rag` giving them the MCP server will need to add `[mcp]` -
a one-line, clearly-messaged change. None of these reintroduce `pywin32` onto the
CLI path, which is the goal. This fully resolves #182/#184 without an upstream
dependency.
