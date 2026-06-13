---
tags:
  - '#research'
  - '#cli-index-default'
date: '2026-05-30'
modified: '2026-05-30'
related: []
---

# `cli-index-default` research: `index --rebuild footgun audit`

## Trigger

Issue #115 asks whether `vaultspec-rag index --type` should become
required like `clean --type` did in PR #109 (Wave 1C, #111).
Grounding revealed the footgun was not the bare `index` invocation
(which is incremental and safe) but the `--rebuild` flag inheriting
the `--type all` default and silently destroying both Qdrant
collections — even when the user explicitly passes `--type vault`.

## Method

One Sonnet audit pass over four areas: current behaviour
(`handle_index` + `--rebuild` interaction), every callsite that
invokes `index` without `--type`, daily-driver cost-of-typing
tradeoff, and a split-safety design alternative.

## Findings

### Current behaviour

- `handle_index` (`cli.py:592-599`) declares `--type` as a typer
  `Option` defaulting to `"all"`. Daily-driver `vaultspec-rag index` runs both vault and code incrementally.
- `--rebuild` (`cli.py:604-610`) defaults to `False`. When set, the
  in-process branch at `cli.py:849-871` calls
  `shutil.rmtree(store.db_path)` — the **shared Qdrant directory** —
  then re-opens the store. The rmtree is **not scoped to the
  collection** named in `--type`. Both vault and code collections
  vanish on any `--rebuild` invocation, regardless of what `--type`
  was passed.
- The MCP fast-path is unaffected: `cli.py:744-753` forwards
  `rebuild` as a boolean to `reindex_vault` / `reindex_codebase`
  separately, which scope correctly.
- So `vaultspec-rag index --rebuild --type vault` in in-process
  mode silently drops `code_collection` too. The README example
  `vaultspec-rag index --rebuild` (root README.md:98) is even
  worse: it inherits `--type all`, so a bare rebuild wipes
  everything.

### Callsites without explicit `--type`

- `tests/test_cli.py:93`: workspace-validation negative test — never
  reaches `--type` logic.
- `tests/test_cli.py:164` (`TestIndexRebuild`): explicit `--type code`. Safe under a required-`--type` change.
- `tests/test_cli_integration.py:87,95,111,120`: all pass explicit
  `--type vault` / `--type code` / `--type all`. Safe.
- `README.md:95,98`: bare `vaultspec-rag index` and bare
  `vaultspec-rag index --rebuild` (the documented form of the
  footgun).
- `src/vaultspec_rag/README.md:39,52,61`: three quick-start
  examples using bare `vaultspec-rag index`.
- `.github/workflows/*.yml`: zero CLI invocations of `index`.
- `.vaultspec/rules/rules/vaultspec-rag.builtin.md:34`: documents
  `index [--type vault|code|all]` (brackets = optional).

### Daily-driver tradeoff

`vaultspec-rag index` is a four-word steady-state operation that
runs after every change. Adding `--type all` every time
(`vaultspec-rag index --type all`) raises the friction for the
dominant pattern. The `clean` analogy is imperfect — `clean` is
explicitly destructive every time and runs on demand, `index` is
incremental and runs constantly. Asymmetry with `clean` is
acceptable; uniform-against-pattern isn't a goal in itself.

### Split-safety alternative

Conditional requirement is achievable in Typer with a manual check
in `handle_index`: keep `--type` defaulting to `all` for incremental
runs, but reject `--rebuild` without an explicit `--type`. Three
scenarios:

- `vaultspec-rag index` → works, type=all, incremental, no friction.
- `vaultspec-rag index --rebuild` → exits 2 with usage error:
  `--rebuild requires an explicit --type (vault|code|all).`
- `vaultspec-rag index --rebuild --type vault` → scoped rebuild
  (which must also be a *truly* scoped rebuild, see scope-bug
  below).

No tests rely on `--rebuild` without `--type` succeeding (the only
rebuild test passes `--type code`). Zero test breakage.

### Scope bug discovered alongside

`cli.py:849-853` does `shutil.rmtree(store.db_path)` on the
shared Qdrant directory then re-opens. This destroys both vault
and code collections unconditionally, even on `--rebuild --type vault`. The `VaultStore` API already exposes `drop_table()` and
`drop_code_table()` (used by `handle_clean` at `cli.py:1029-1032`)
that scope correctly. Swapping to those closes the second half of
the footgun: a scoped rebuild really only rebuilds that scope.

## Recommendation

Two-part fix, both in scope for #115:

1. Require `--type` explicitly whenever `--rebuild` is set. Bare
   `vaultspec-rag index` keeps working unchanged.
1. Replace `shutil.rmtree(store.db_path)` in the in-process
   rebuild branch with `store.drop_table()` / `store.drop_code_table()`
   gated on `index_type`, mirroring `handle_clean`.

This closes the footgun without breaking the daily-driver UX and
without requiring users to type more for the safe-by-default
invocation. The asymmetry with `clean --type required` is
intentional — `clean` has no safe default; `index` does.
