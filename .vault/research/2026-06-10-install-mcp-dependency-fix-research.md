---
tags:
  - '#research'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
modified: '2026-06-10'
related: []
---

# `install-mcp-dependency-fix` research: `issue 182 mcp dependency and pywin32 ownership`

Issue #182 reports that `vaultspec-rag server start` (and `server mcp start`)
crash at import time in a clean production install, surfacing on Windows as
`ModuleNotFoundError: No module named 'pywintypes'`. This research separates the
two defects tangled in that report, establishes which one this repository owns,
and tests the reporter's "version skew" evidence and the proposed
`os.add_dll_directory` DLL shim against the actual packaging behaviour. The goal
is a clean install of `vaultspec-rag` that declares all of its true runtime
dependencies without managing the internals of packages it does not own.

## Findings

### F1 — The owned defect: `mcp` is a hard runtime dependency declared only as an extra

The daemon entry point `src/vaultspec_rag/server/_main.py` performs an
unconditional runtime import (`from ..mcp import mcp`), and the entire
`src/vaultspec_rag/mcp/` package depends on the third-party `mcp` distribution:
`src/vaultspec_rag/mcp/_mcp.py` does `from mcp.server.fastmcp import FastMCP` at
module scope. The HTTP daemon transport itself is `mcp.streamable_http_app()`,
so `mcp` is core server functionality — not an MCP-stdio-only optional surface.

Despite this, `pyproject.toml` lists `mcp>=1.26.0` only under
`[project.optional-dependencies]` as the `dev` and `mcp` extras. It is absent
from the core `dependencies` array. A consumer who runs a plain
`pip install vaultspec-rag` (no extras) therefore receives `mcp` only by
accident: the core dependency `vaultspec-core>=0.1.27` lists `mcp` as one of its
own core requirements and drags it into the resolution. The dev environment
masks the bug for the same reason. This is a genuine dependency-definition
divergence owned entirely by this repository.

Scope check: the `mcp` requirement is the **server's**, not the whole package's.
The CLI search-delegation fast path (`src/vaultspec_rag/cli/_http_search.py`)
talks to the running service over plain `urllib`, not the `mcp` client library.
Indexing, search, status, and clean do not import `mcp`. The fix is therefore to
declare `mcp` as a core runtime dependency (the resident service is the
package's primary mode), not to invent a new optional boundary.

### F2 — The secondary symptom is upstream MCP bug #2233, still unreleased

Once `mcp` is imported, `mcp/__init__.py` eagerly imports `mcp.client.stdio`,
which on Windows imports `mcp/os/win32/utilities.py`, which executes
`import pywintypes` at module load. This makes `pywin32` a hard import for every
Windows consumer of `mcp` — including pure server deployments that never use the
stdio client. This is tracked upstream as `modelcontextprotocol/python-sdk`
issue #2233. The proposed fix, PR #2365 (remove the eager `client.stdio` import
from `mcp/__init__.py` and move `pywin32` behind a new `stdio` install extra),
is still **open and unreleased**; `mcp` 1.27.2 is the latest stable release and
still imports `pywin32` eagerly. There is currently no `mcp` version floor that
removes the eager import, so we cannot pin our way past it today.

### F3 — The reported "version skew" is a red herring

The report cites `pywin32-312.dist-info` alongside a shipped `pywintypes313.dll`
as evidence of a corrupt install. This is normal `pywin32` packaging: the `313`
suffix is the **CPython 3.13 ABI tag**, not a `pywin32` build number. The build
number here is `312` (confirmed by `pywin32.version.txt`). The working
development venv on this machine ships the identical pairing —
`pywin32-312.dist-info`, `pywintypes313.dll`, `pythoncom313.dll` — and
`import pywintypes` succeeds. So the version-suffix mismatch neither proves nor
explains the reporter's failure; it is expected.

### F4 — Why it imports here but failed for the reporter

In the working venv, `pywin32.pth` adds `win32`, `win32\lib`, and `pythonwin`
to `sys.path`, the `pywin32_system32` directory is present, and the `pywintypes`
loader resolves the DLL from there (verified: `pywintypes.__file__` points at
`pywin32_system32/pywintypes313.dll`). Notably the `pywin32_bootstrap.py` file
that `pywin32.pth` references is absent even in this working venv, yet import
still succeeds — so the failure mode is the broader "the venv's `pywin32` DLL
linkage never got established" class, which `uv` and `pip` are both prone to
because neither runs `pywin32_postinstall.py`. This is a `pywin32`×installer
ecosystem issue, reproducible independent of `vaultspec-rag`, and not a defect
in this package's metadata or code.

### F5 — Ownership verdict: do not ship an `os.add_dll_directory` DLL shim

A runtime shim that locates `pywin32_system32` and calls `os.add_dll_directory`
before importing `mcp` would paper over F2/F4, but it means this package would
be managing the DLL search path of `pywin32` — a transitive dependency of `mcp`
that `vaultspec-rag` neither declares nor owns. That is the wrong layer and
violates the standing project principle that we do not manage dependencies for
code we do not own. It is also fragile: it hard-codes assumptions about another
project's wheel layout that can change between `pywin32` releases. The shim is
rejected.

### F6 — Recommended direction (carried into the ADR)

- **Primary, owned fix:** promote `mcp>=1.26.0` into the core `dependencies`
  array in `pyproject.toml`; collapse the now-redundant `mcp` extra to a
  deprecated no-op alias so `pip install vaultspec-rag[mcp]` still resolves;
  drop the duplicate from the `dev` extra/group to keep a single source of
  truth.
- **Actionable error (messaging, not dependency management):** guard the
  `from ..mcp import mcp` import in the server entry point so a missing or
  non-functional `mcp`/`pywin32` raises a clear, actionable message (point
  Windows/`uv` users at the known `pywin32` remediation) instead of an opaque
  `ModuleNotFoundError` deep in a transitive module.
- **Track upstream:** watch `modelcontextprotocol/python-sdk` #2233 / PR #2365;
  once the eager-import fix ships in a released `mcp`, add a `mcp>=<fixed>`
  floor so server-only installs stop importing `pywin32` altogether — the real
  fix, achieved with only a version floor and no DLL management.
- **Regression guard:** a packaging-metadata test that parses
  `importlib.metadata.requires("vaultspec-rag")` and asserts `mcp` is a core
  requirement (present without an `extra ==` marker), directly pinning the F1
  defect closed.

### Open question for the ADR / decision phase

Whether to also surface the Windows `pywin32`/`uv` remediation in install
documentation or only in the guarded import's error text, and whether to file
the upstream-pin follow-up as a tracked issue now so the `mcp>=<fixed>` floor is
not forgotten once #2233 lands.
