---
tags:
  - '#plan'
  - '#cli-index-default'
date: '2026-05-30'
modified: '2026-07-25'
related:
  - '[[2026-05-30-cli-index-default-adr]]'
  - '[[2026-05-30-cli-index-default-research]]'
---

# `cli-index-default` `index rebuild safety: require --type, scoped drop` plan

Implements gh issue #115. Two-part fix grounded by the research
audit: (1) `--rebuild` now requires an explicit `--type`; (2) the
in-process rebuild branch drops only the selected collection
instead of nuking the whole shared Qdrant directory.

### Phase `P01` - Require an explicit type with a rebuild

Refuse a rebuild that did not name its scope, distinguishing a user-supplied type from the default, and report the refusal through the structured envelope on both output paths.

- [x] `P01.S01` - Refuse a rebuild whose type was left at its default by inspecting the invocation's parameter source, and emit a rebuild-requires-explicit-type refusal that names the valid invocations, carried through the structured envelope in JSON mode and a non-zero exit in both modes; `src/vaultspec_rag/cli/_index.py`.

### Phase `P02` - Scope the rebuild drop to the selected collection

Replace the whole-directory removal with a per-collection drop gated on the selected type, so a scoped rebuild can no longer destroy the other collection.

- [x] `P02.S02` - Replace the shared-directory removal in the in-process rebuild path with a per-collection drop gated on the selected type, so rebuilding one collection leaves the other intact; `src/vaultspec_rag/cli/_index.py`.

### Phase `P03` - Documentation

Correct every documented rebuild invocation to name its type, and state the requirement and the honoured scope.

- [x] `P03.S03` - Correct the documented rebuild invocations to name an explicit type in the project README, the package README, and the shipped discovery rule, and state that the scope is honoured; `README.md`.

### Phase `P04` - Tests and smoke

Cover the refusal in both output modes, prove a scoped rebuild leaves the other collection intact, and confirm the unchanged bare-index path.

- [x] `P04.S04` - Cover the refusal in human and JSON mode and confirm a rebuild naming its type proceeds; `src/vaultspec_rag/tests/test_cli_index.py`.
- [x] `P04.S05` - Prove with an integration test over both populated collections that rebuilding one leaves the other's point count unchanged; `src/vaultspec_rag/tests/integration/`.
- [x] `P04.S06` - Confirm by hand that a bare index run is unaffected, an unscoped rebuild refuses with a non-zero exit, and a scoped rebuild spares the other collection; `src/vaultspec_rag/tests/integration/`.

## Description

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

## Steps

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
