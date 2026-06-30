---
tags:
  - '#adr'
  - '#cli-index-default'
date: '2026-05-30'
modified: '2026-06-30'
related:
  - '[[2026-05-30-cli-index-default-research]]'
---

# `cli-index-default` adr: `require --type with --rebuild, scope drop to collection` | (**status:** `accepted`)

## Problem Statement

PR #109 made `clean --type` required because every invocation was
destructive. Issue #115 asks whether `index --type` should follow
suit. Grounding revealed that bare `vaultspec-rag index` is safe
(incremental, idempotent) and is the canonical quick-start example
in three places. The actual footgun is `--rebuild` inheriting the
`--type all` default, which silently destroys both Qdrant
collections — and grounding surfaced a second bug: the in-process
rebuild branch (`cli.py:849-853`) uses
`shutil.rmtree(store.db_path)` on the shared Qdrant directory, so
even `--rebuild --type vault` wipes the code collection too.

## Considerations

- The asymmetry argument with `clean` is a false parallel. `clean`
  has no safe default; `index` does. Forcing `--type` everywhere
  for symmetry's sake punishes the dominant safe pattern.
- The daily-driver pattern is `vaultspec-rag index` after every
  workspace change. Raising friction here is a regression for the
  common case to fix the uncommon-but-destructive case.
- The footgun is `--rebuild`-shaped, not `--type`-shaped. The
  smallest cut that closes the issue is conditional on `--rebuild`
  being set.
- The store's `drop_table` / `drop_code_table` methods already
  exist and are used by `handle_clean`. The in-process rebuild's
  whole-directory rmtree is an older, broader approach that
  predates the scoped drops.

## Constraints

- Backwards compatibility: bare `vaultspec-rag index` must keep
  working unchanged (the README quick-start at three places).
- The error message for `--rebuild` without `--type` must be
  self-documenting: state exactly what `--type all` would do and
  what the user must add to opt in explicitly.
- `--rebuild --type X` must really only rebuild X (the scope-bug
  fix). No more silent cross-scope destruction.
- The MCP fast-path already scopes rebuild correctly per tool;
  this ADR changes only the in-process branch + the CLI-level
  validation that runs before either branch.

## Implementation

### CLI guard (`src/vaultspec_rag/cli.py:handle_index`)

After the existing dry-run early-return and before the `--port`
branch, add a manual check using
`ctx.get_parameter_source("index_type")` (Click API exposed by
Typer's context): if the source is `DEFAULT` (i.e. the user did
not type `--type`) and `--rebuild` is set, raise a usage error
through the JSON-mode-aware error helper from #112.

Error envelope follows the contract:
`{"ok": false, "command": "index", "error": "rebuild_requires_explicit_type", "message": "--rebuild requires an explicit --type ...", "remediation": [...]}`.

### Scoped rebuild (`src/vaultspec_rag/cli.py` in-process branch)

Replace `shutil.rmtree(store.db_path)` with
`store.drop_table()` and/or `store.drop_code_table()` gated on
`do_vault` / `do_code`. The store instance stays valid; subsequent
`incremental_index` / `full_index(clean=True)` calls operate
against the scoped empty state.

### Docs

- Root `README.md`: update the bare `vaultspec-rag index --rebuild`
  example to `vaultspec-rag index --rebuild --type all`.
- `src/vaultspec_rag/README.md`: same. The three bare-`index`
  quick-start examples stay as-is.
- `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: note that
  `--rebuild` requires explicit `--type` and that `--rebuild --type X` is scoped to X.

### Tests

- One new test asserting `vaultspec-rag index --rebuild`
  (no `--type`) exits 2 with `rebuild_requires_explicit_type`.
- One new test asserting `--json` mode emits the matching
  envelope.
- One new integration test asserting `--rebuild --type vault`
  leaves the code collection intact (proves the scope-bug fix).

## Rationale

Conditional requirement (Option B from the research) was chosen
over make-`--type`-required-always (Option A) because the
daily-driver pattern stays unchanged and the asymmetry with
`clean` is intentional. Doing nothing (Option C) was rejected
because the rebuild + default-all combo is a real, latent
destructive surface.

The collection-scoped drop ships in the same PR because the
required-`--type` guard would be a hollow promise without it —
otherwise `--rebuild --type vault` would still silently destroy
the code collection, making the new guard's narrative dishonest.

## Consequences

- One new behaviour change: `vaultspec-rag index --rebuild`
  (no `--type`) now exits 2. The audit found no tests or
  workflows that rely on the previous form; README example is
  updated; error message tells the user exactly what to add.
- `--rebuild --type vault` and `--rebuild --type code` now do
  what their flag combination claims: scoped destruction.
- The `clean` / `index` asymmetry is now explicitly documented as
  intentional. Future commands should look at destructiveness,
  not symmetry, when deciding whether to make flags required.
