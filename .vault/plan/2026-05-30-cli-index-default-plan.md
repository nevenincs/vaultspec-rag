---
tags:
  - '#plan'
  - '#cli-index-default'
date: '2026-05-30'
modified: '2026-06-30'
related:
  - '[[2026-05-30-cli-index-default-adr]]'
  - '[[2026-05-30-cli-index-default-research]]'
---

# `cli-index-default` `index rebuild safety: require --type, scoped drop` plan

Implements gh issue #115. Two-part fix grounded by the research
audit: (1) `--rebuild` now requires an explicit `--type`; (2) the
in-process rebuild branch drops only the selected collection
instead of nuking the whole shared Qdrant directory.

## Proposed Changes

- `handle_index` (`cli.py`): inspect the typer context to detect
  whether `--type` was user-supplied; if `--rebuild` is set and
  `--type` was not user-supplied, exit 2 with
  `rebuild_requires_explicit_type` envelope (JSON-aware via the
  Wave 2 #112 helper).
- In-process rebuild branch: replace `shutil.rmtree(store.db_path)`
  with `store.drop_table()` / `store.drop_code_table()` gated on
  `do_vault` / `do_code` so `--rebuild --type X` only destroys X.
- README examples updated for the new contract.
- Tests cover the guard (Rich + JSON) and the scope fix.

## Tasks

### Phase 1 — CLI guard

1. In `handle_index`, change the signature to take a
   `typer.Context` parameter (already present — verify).
1. Right after the dry-run early return, query
   `ctx.get_parameter_source("index_type")`. When `rebuild` is
   `True` and the source is `ParameterSource.DEFAULT`, emit a
   `rebuild_requires_explicit_type` error via
   `_emit_json_error_and_exit` when `json_mode` else a
   `console.print` red + `typer.Exit(code=2)`. Error message
   spells out the three valid invocations
   (`--rebuild --type vault|code|all`).

### Phase 2 — Scoped rebuild

1. Replace the in-process rebuild block (`cli.py:849-871`):
   - Drop the `shutil.rmtree(store.db_path)` call.
   - Drop the `store.close()` + `_open_vault_store` re-open
     dance (no longer needed once we use scoped drop).
   - Replace with `if do_vault: store.drop_table()` and
     `if do_code: store.drop_code_table()` calls.
   - The existing `incremental_index` / `full_index(clean=True)`
     calls remain. `full_index(clean=True)` already handles
     drop-and-recreate at the indexer level, but the dropped
     collection still needs the ensure-call. Verify
     `VaultIndexer.full_index` / `CodebaseIndexer.full_index`
     handle the ensure themselves (per ADR memory: `clean=True drops and recreates collection`). If not, call
     `store.ensure_table()` / `store.ensure_code_table()` after
     the drop.

### Phase 3 — Docs

1. `README.md:98`: replace `vaultspec-rag index --rebuild` with
   `vaultspec-rag index --rebuild --type all` (or split into two
   examples showing both `--type vault` and `--type all`).
1. `src/vaultspec_rag/README.md`: same; explicitly document that
   `--rebuild` requires `--type` and that the scope is honored.
1. `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: extend the
   `index` summary line with the rebuild rule.

### Phase 4 — Tests

1. Unit test: `vaultspec-rag index --rebuild` (no `--type`) exits
   2, output contains `rebuild_requires_explicit_type` or the
   error prose.
1. Unit test: `vaultspec-rag index --rebuild --json` (no
   `--type`) emits the envelope shape with
   `error="rebuild_requires_explicit_type"`.
1. Unit test: `vaultspec-rag index --rebuild --type vault --dry-run` proceeds (dry-run short-circuits before the guard
   would fire on bare invocations; the guard must fire after
   dry-run early-return). Actually re-examine: dry-run is
   `--type code|all` only. So the test is `--rebuild --type code --dry-run` proceeds without error.
1. Integration test in `tests/integration/test_codebase_integration.py`
   (or `tests/integration/test_api_integration.py`): index both
   vault and code; then run `index --rebuild --type vault`
   in-process; assert the code collection still has the
   original count.

### Phase 5 — Smoke + commit

1. Smoke: bare `vaultspec-rag index` against the rag worktree
   itself, confirm it still works (no friction). Then
   `vaultspec-rag index --rebuild` (no `--type`), confirm exit 2
   - error. Then `--rebuild --type vault`, confirm code
     collection survives.
1. Commit one feat() with a clear two-part description; push;
   open PR linking #115; ignore Gemini; merge after CI green.

## Parallelization

Phase 1 and Phase 2 touch the same function but disjoint
sections; one commit is cleaner than two. Phase 3 docs depend on
both phases. Phase 4 tests depend on Phase 1 + 2 wired.

## Verification

- 114 unit tests + new ones pass.
- Integration test for the scope-bug fix passes.
- Smoke confirms bare `index` unchanged, `index --rebuild` now
  errors helpfully, `--rebuild --type X` is properly scoped.
- ruff + mdformat + vault check schema clean.
