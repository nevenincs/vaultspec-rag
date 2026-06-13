---
tags:
  - '#plan'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
modified: '2026-06-10'
tier: L1
related:
  - '[[2026-06-10-install-mcp-dependency-fix-adr]]'
  - '[[2026-06-10-install-mcp-dependency-fix-research]]'
---

# `install-mcp-dependency-fix` `declare mcp core dependency and guard server import` plan

- [x] `S01` - Promote mcp to core dependencies, collapse the mcp extra to a deprecated no-op alias kept for backward-compat, and drop the duplicate mcp from the dev extra and dev dependency-group; `pyproject.toml`.
- [x] `S02` - Guard the unconditional mcp import in main with try/except re-raising a chained RuntimeError carrying an actionable uv and pywin32 remediation message, messaging only with no DLL handling; `src/vaultspec_rag/server/_main.py`.
- [x] `S03` - Add a packaging-metadata regression test asserting importlib.metadata.requires reports mcp as a core requirement with no extra marker; `src/vaultspec_rag/tests/test_packaging_metadata.py`.
- [x] `S04` - Run uv sync, ruff, basedpyright and the unit suite, verify the server entry import path is clean, file the upstream mcp 2233 version-floor follow-up issue, then commit; `pyproject.toml`.
  Fix the issue #182 install blocker by declaring `mcp` as a core dependency and guarding the server import, without managing `pywin32`'s DLLs.

## Description

This plan implements the accepted ADR for issue #182. The daemon imports the
third-party `mcp` distribution unconditionally, yet the package declares it only
as an optional extra, so a clean install crashes the moment the server starts
(on Windows surfacing as a `pywintypes` error). The research established that the
metadata under-declaration is the owned defect, while the `pywin32` failure is an
upstream `mcp` bug plus a `uv` post-install gap that this package must not paper
over.

S01 makes the metadata honest by promoting `mcp` into the core dependency array
and retiring the redundant extra to a backward-compatible no-op. S02 converts the
residual Windows failure from an opaque transitive traceback into an actionable
guarded-import error, messaging only. S03 pins the defect closed with a real
packaging-metadata assertion. S04 runs the quality gates, files the deferred
upstream version-floor follow-up, and commits. The rejected DLL shim and the
deferred `mcp` version floor are explicitly out of scope.

## Steps

## Parallelization

S01 and S02 are independent and may be done in either order. S03 depends on S01
(it asserts the metadata change S01 makes). S04 is the closing gate and must run
last, after S01 to S03 are complete.

## Verification

- `importlib.metadata.requires("vaultspec-rag")` reports an `mcp` requirement
  with no `extra ==` marker, and the new packaging-metadata test asserting this
  passes.
- A fresh resolve (`uv sync`) succeeds and `mcp` appears as a core dependency in
  the lockfile, not only via `vaultspec-core`.
- Importing the server entry point with `mcp` present succeeds; the guarded
  import path raises the actionable `RuntimeError` (chained from the original
  `ImportError`) when `mcp` cannot be imported, rather than leaking an opaque
  `ModuleNotFoundError`.
- `ruff check` and `basedpyright` are clean on the changed files; the unit suite
  passes.
- A follow-up issue tracking the upstream `mcp` #2233 version-floor is filed.

The plan is complete when every Step is closed (`- [x]`) and the above checks
hold.
