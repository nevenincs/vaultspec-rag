---
tags:
  - '#adr'
  - '#module-split'
date: '2026-06-01'
modified: '2026-06-01'
related:
  - "[[2026-06-01-module-split-research]]"
  - "[[2026-06-01-module-split-audit]]"
---

# `module-split` adr: monolith-to-package split via `__init__` re-export | (**status:** `accepted`)

## Problem Statement

Several source modules have grown into monoliths — `cli.py` (4286 lines),
`indexer.py` (2099), `mcp_server.py` (1641), `torch_config.py` (1263),
`search.py` (952), `commands.py` (943) — which the module-split audit flagged
as hard to navigate, review, and extend (ADR-B's #142 work would bloat the two
worst offenders further). This ADR fixes the strategy for breaking each
oversized module into a package while guaranteeing the public import surface is
unchanged, so no production caller or test must be edited.

## Considerations

- **The re-export contract is the spine.** Each `module.py` becomes a package
  `module/` whose `__init__.py` re-exports the *verbatim* pre-split public
  surface through an explicit `__all__`. That surface includes the
  `_`-prefixed helpers that tests import directly (e.g. `cli._spawn_service`,
  `mcp_server._ensure_watcher`, `commands._classify_uv_sync_result`): they are
  de-facto public and must stay importable from the package root.
- **Cohesive code moves into `_`-prefixed submodules**; shared module-level
  state stays in the package `__init__`.
- **`mcp_server` is special.** The module-level `mcp = FastMCP(...)` drives the
  `@mcp.tool()`/`@mcp.resource()`/`@mcp.prompt()` decorators. The package
  `__init__` owns `mcp` and the other shared globals (`_registry`,
  `_watcher_*`, `_SERVICE_TOKEN`, `_http_mode`), then imports the tool
  submodules so their decorators register against the one instance. The
  console-script entry point `vaultspec_rag.mcp_server:main` must remain
  importable from the package root.
- **Ordering.** Execute low-risk → high-risk to validate the pattern early:
  `commands`, `torch_config`, `search`, `indexer`, `cli`, then `mcp_server`.

## Constraints

- **No public-surface change.** Tests must pass *unedited*. The full relevant
  test suite plus ruff, ruff-format, and ty must be green after each module
  split; that is the gate.
- **Circular-import hazard (mcp_server).** Tool submodules import `mcp` from the
  package while the package imports the submodules — the `__init__` must define
  globals before importing submodules.
- **Typer registration order (cli).** The app and sub-apps must be created and
  nested before any command decorator runs; the app submodule imports first.
- **Stable parents.** This is a pure structural refactor of in-repo modules; no
  new dependency, no frontier risk. `store.py` is explicitly out of scope (kept
  single-file — one cohesive class).

## Implementation

For each in-scope module, create the package directory, move each cohesive
section into a `_`-prefixed submodule per the audit's section map, write
`__init__.py` to import from the submodules and re-export the exact prior
surface via `__all__`, and delete the original `module.py`. Intra-module
references become submodule imports; shared state and (for `mcp_server`) the
`mcp` instance live in `__init__`. The entry point and all decorator
registrations are preserved. Each module is one plan phase, landed only when
the full suite is green and the linters/type-checker are clean.

## Rationale

The audit established that every oversized module except `store.py` has natural
internal seams and a well-defined external surface, so the package + re-export
pattern decomposes them without an API break. Making "no public-surface change"
the hard gate means the existing 640+ tests are the safety net; any regression
shows up immediately. Sequencing the riskiest module (`mcp_server`, with FastMCP
registration and the entry point) last lets the pattern prove itself on simpler
modules first.

## Consequences

- **Gains.** Smaller, navigable, reviewable files; new feature code (e.g. #142)
  lands in focused submodules instead of growing a monolith; clearer ownership.
- **Honest difficulties.** This is a large mechanical refactor touching ~10k
  lines; the risk is a missed re-export or, for `mcp_server`, a decorator-order
  / circular-import bug. The full-suite gate and risk-ascending order mitigate
  this. Test files that import deep private helpers keep working only because
  `__all__` re-exports them — a deliberate, documented coupling.
- **Pitfalls.** `__init__` import order matters (apps-before-commands;
  globals-before-tool-submodules). `store.py` stays whole by design.

## Codification candidates

- **Rule slug:** `module-package-reexport-preserves-surface`.
  **Rule:** When a module is split into a package, its `__init__.py` must
  re-export the verbatim pre-split public surface (an explicit `__all__` that
  includes any `_`-prefixed names imported elsewhere) so no import changes and
  tests pass unedited.
