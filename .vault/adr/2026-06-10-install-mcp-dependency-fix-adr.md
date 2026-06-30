---
tags:
  - "#adr"
  - "#install-mcp-dependency-fix"
date: '2026-06-10'
related:
  - "[[2026-06-10-install-mcp-dependency-fix-research]]"
superseded_by: '2026-06-18-mcp-service-client-adr'
modified: '2026-06-30'
---

# `install-mcp-dependency-fix` adr: `declare mcp as a core dependency; reject pywin32 dll shim` | (**status:** `superseded`)

## Problem Statement

Issue #182 is a critical install blocker: a clean production install of
`vaultspec-rag` crashes the moment `server start` (or `server mcp start`) runs,
because the daemon imports the third-party `mcp` distribution unconditionally
while the package metadata declares `mcp` only as an optional extra. On Windows
under `uv` the crash surfaces one layer deeper as
`ModuleNotFoundError: No module named 'pywintypes'`. Research
`[[2026-06-10-install-mcp-dependency-fix-research]]` separated the two defects:
one (the metadata under-declaration) is owned by this repository; the other (the
`pywin32` import) is an upstream `mcp` defect compounded by a `pywin32`×`uv`
ecosystem gap. This ADR records which defect we fix, how, and — equally
important — which tempting fix we deliberately reject.

## Considerations

- The daemon entry point imports `mcp` unconditionally, and the HTTP transport
  is literally `mcp.streamable_http_app()`. `mcp` is core server functionality,
  not an MCP-stdio-only optional surface (research F1).
- Plain `pip install vaultspec-rag` resolves `mcp` only by accident, because the
  core dependency `vaultspec-core>=0.1.27` drags it in transitively. The dev
  environment masks the bug for the same reason.
- The `mcp` requirement belongs to the **server**, not the whole package: the
  CLI search-delegation path uses `urllib`, and index/search/status/clean never
  import `mcp`. But the resident service is the package's primary mode, so a core
  dependency (not a new optional boundary) is the right call.
- The Windows `pywintypes` failure is upstream `modelcontextprotocol/python-sdk`
  issue #2233 (eager `mcp.client.stdio` import forces `pywin32` on all Windows
  users). The fix, PR #2365, is open and unreleased; `mcp` 1.27.2 is latest and
  still imports `pywin32` eagerly (research F2).
- The report's `pywin32-312` vs `pywintypes313.dll` "version skew" is a red
  herring — `313` is the CPython 3.13 ABI tag, identical in the working dev venv
  (research F3).
- A standing project principle (memory feedback) is that we do not manage
  dependencies for code we do not own.

## Constraints

- **Upstream dependency, not yet landed:** the clean elimination of the
  `pywin32` import depends on `mcp` shipping the #2233/PR #2365 fix in a released
  version. Until then no `mcp` version floor removes the eager import, so the
  full Windows resolution is gated on an external project. This ADR must
  therefore deliver value without waiting on upstream.
- **No DLL management:** any fix that reaches into `pywin32`'s wheel layout
  (`pywin32_system32`, `os.add_dll_directory`) is out of bounds — it is the wrong
  layer and is fragile across `pywin32` releases (research F5).
- **Backward compatibility:** consumers who already install
  `vaultspec-rag[mcp]` must keep resolving without error after the extra is
  reorganised.
- **Test mandate:** the regression guard must be a real packaging-metadata
  assertion (no mocks/skips), consistent with the project's testing rules.

## Implementation

Four changes, all owned by this repository, plus one tracked deferral.

First, promote `mcp>=1.26.0` into the core `dependencies` array of
`pyproject.toml` so the metadata declares the hard runtime requirement the code
already has. The `mcp` optional-dependency extra collapses to a deprecated
no-op alias so existing `vaultspec-rag[mcp]` installs keep resolving, and the
duplicate `mcp` line is removed from the `dev` extra and the `dev` dependency
group, leaving the core array as the single source of truth.

Second, guard the unconditional `from ..mcp import mcp` in the server entry
point. A failed import (whether a missing `mcp` or a non-functional Windows
`pywin32`) is caught and re-raised as a clear, actionable message that names the
likely `uv`/`pywin32` post-install cause and the remediation, instead of an
opaque `ModuleNotFoundError` surfacing from deep inside a transitive module.
This is messaging, not dependency management.

Third, add a packaging-metadata regression test that reads
`importlib.metadata.requires("vaultspec-rag")` and asserts `mcp` is present as a
core requirement — i.e. without an `extra == ...` environment marker. This pins
the F1 defect closed at the metadata layer where it actually lives.

Fourth (deferred, tracked): once upstream `mcp` ships the #2233 fix in a
released version, add a `mcp>=<fixed>` floor so server-only installs stop
importing `pywin32` altogether. This is the real elimination of the Windows
failure and costs only a version floor — no DLL handling. A follow-up issue
records this so it is not forgotten when #2233 lands.

Explicitly rejected: a runtime `os.add_dll_directory` shim that links
`pywin32`'s DLLs before importing `mcp`. It would mask the symptom but at the
cost of this package managing a transitive dependency's DLL search path —
rejected on both the ownership principle and fragility grounds (research F5).

## Rationale

The research is unambiguous on ownership: F1 shows the metadata
under-declaration is ours and trivially correct to fix; F2–F4 show the
`pywin32` failure originates upstream and in the installer ecosystem, not in our
code or metadata; F5 rejects the shim as wrong-layer. Declaring `mcp` as a core
dependency makes the metadata honest about what the code does and removes the
accidental reliance on `vaultspec-core`'s transitive pull — that alone resolves
the primary crash class (`No module named 'mcp'`) for every consumer. The
guarded import converts the residual Windows `pywin32` failure from an opaque
stack trace into an actionable instruction without overstepping into another
project's packaging. The deferred version floor captures the durable fix at the
correct layer the moment upstream makes it available.

## Consequences

- A clean `pip/uv install vaultspec-rag` now declares all of its true runtime
  dependencies; the server no longer depends on `vaultspec-core` happening to
  pull `mcp`.
- Windows/`uv` users who still hit the `pywin32` linkage gap get a clear message
  and a remediation path rather than a confusing transitive traceback — but the
  underlying `pywin32` import is not fully eliminated until the upstream fix
  ships and we add the version floor. This ADR is honest that the Windows story
  is two-staged.
- The `[mcp]` extra becomes a no-op alias; its documentation must note it is
  retained only for backward compatibility.
- A new external dependency is introduced into our roadmap: the tracked
  follow-up to add the `mcp>=<fixed>` floor. If #2233 stalls upstream, the
  guarded-import message remains the user-facing mitigation indefinitely, which
  is acceptable.

## Codification candidates

- **Rule slug:** `no-managing-unowned-dependency-internals`.
  **Rule:** Never reach into the wheel layout, DLL search path, or post-install
  internals of a transitive dependency the project does not own (e.g. a runtime
  `os.add_dll_directory` shim for `pywin32`); fix the symptom at the layer the
  project controls — its own metadata, a guarded import with an actionable
  error, or a version floor that tracks the upstream fix.
