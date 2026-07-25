---
tags:
  - '#research'
  - '#install-command'
date: '2026-04-12'
modified: '2026-07-25'
related:
  - '[[2026-04-12-vaultspec-rag-install-reference]]'
  - '[[2026-04-12-vaultspec-rag-install-adr]]'
---

# `install-command` research

Pre-ADR investigation that grounded the architectural decisions for
`vaultspec-rag install` and `vaultspec-rag uninstall` (issues #54 and
#55). The detailed findings live in
`[[2026-04-12-vaultspec-rag-install-reference]]`; this document
captures the question set and what the investigation determined about
each one.

## Questions Investigated

### Layer separation and module placement

- Where does install orchestration live in vaultspec-core today?
- Does core have a module literally named `install.py`, and if so where?
- What is the dependency direction between core's `cli/` and `core/`
  subpackages?
- Which conventions in the vault history (prior ADRs and audits)
  document the layer separation rule for vaultspec packages?

### Public API surface for downstream callers

- Which symbols in vaultspec-core are stable, public, and intended for
  downstream use by companion packages?
- What are the exact signatures of `install_run`, `uninstall_run`, and
  `sync_provider`? Do they accept the parameters rag needs (target
  path, dry-run, force, skip)?
- What return-shape do they produce, and is it documented as stable?
- What typed exceptions does core raise from these functions, and are
  they re-exported from `vaultspec_core.core`?

### CLI flag surface

- What are core's exact Typer command signatures for `install`,
  `uninstall`, and `sync`? Flag names, short forms, defaults?
- Which flags are shared across the three commands?
- What is the semantic difference between core's `--remove-vault` and
  any rag-specific data-removal flag?
- Does core take a positional `provider` argument? Does it apply to
  rag's enrollment surface?

### Sync auto-discovery and propagation

- Does `vaultspec-core sync` auto-discover companion-supplied source
  files in `.vaultspec/rules/mcps/` and `.vaultspec/rules/rules/`, or
  does it only handle hardcoded core-owned filenames?
- What is the merge strategy for `.mcp.json` — additive, reconciling,
  or something else? How are user-added entries distinguished from
  managed entries?
- For rule and skill propagation to provider directories, is there a
  shared sync engine, and does it support pruning of orphaned
  destinations?

### Symmetric install/uninstall flow

- Can rag's uninstall be implemented as a pure mirror of install
  (delete source files, then call core's sync to propagate the
  removal), or does it need a targeted removal API for `.mcp.json`?
- If symmetric, does core's existing sync support pruning orphans
  whose source files have been removed? If not, what is the minimum
  fix in core to enable it?
- How is ownership tracked so user-added entries are never pruned by
  accident?

### rag's existing structure and dependencies

- What is rag's current src/ layout? Flat or layered?
- Does rag already declare `vaultspec-core` as a dependency? At what
  version pin?
- Where does Typer wiring live in rag's CLI today? How are existing
  commands registered?
- What are rag's existing test conventions (fixtures, markers,
  filesystem patterns)?

## Investigation Outcomes

The reference document captures the concrete code excerpts and
file:line references that answer each question. Key conclusions that
shaped the ADR:

- Core has no `install.py` module; orchestration lives in
  `core/commands.py`. rag must mirror this — no top-level `install.py`.
- The rag-side orchestration file is named `commands.py` to match
  core's role and to position the file for a future layered refactor.
- Direct Python imports of `vaultspec_core.core.commands.sync_provider`
  are the canonical delegation path; rag already declares core as a
  hard dependency.
- Core's `sync_provider` already auto-discovers
  `.vaultspec/rules/{rules,mcps}/` content, so rag only needs to drop
  its files and call sync — no per-file registration logic needed in
  rag.
- `mcp_sync()` in core was the only sync surface that was purely
  additive; rules/agents/skills were already reconciling. The minimal
  fix to make uninstall symmetric is teaching `mcp_sync()` to prune
  orphans, with ownership tracked via a reserved sidecar key in
  `.mcp.json`. This fix ships in the sister core PR (vaultspec-core
  0.1.10).
- 100% CLI flag alignment with core is achievable for every flag
  whose meaning is shared. The one divergence (`--remove-data` vs
  `--remove-vault`) is intentional because the *scope* of removal
  differs (rag's index vs core's user vault docs).

## Method

Investigation was performed by parallel sub-agents against:

- `C:/projects/worktrees/main/src/vaultspec_core/` —
  core's source tree, focused on `cli/`, `core/`, `builtins/`,
  and `config/`.
- `C:/projects/worktrees/feature-54-55-install-command/src/vaultspec_rag/` —
  rag's existing layout and dependency declarations.
- `.vault/adr/` and `.vault/audit/` of both repos — prior decisions
  on layer separation, ecosystem integration, and module exports.

Each agent produced a structured findings report under 1500 words
that fed directly into the reference audit and the ADR.
