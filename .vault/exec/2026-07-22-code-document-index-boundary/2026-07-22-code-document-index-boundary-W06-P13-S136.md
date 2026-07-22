---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S136'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Remove the first-failure and narrowed-marker shortcuts from the test recipe so the harness gate reports the complete result

## Scope

- `justfile`

## Description

- Read `pyproject.toml`'s `[tool.pytest.ini_options]` markers block to confirm the registered marker set (`unit`, `integration`, `cuda`, `subprocess_gpu`, `performance`, `quality`, `robustness`, `timeout`, `xdist_group`).
- Measured actual collection per marker expression with `uv run --no-sync pytest src/vaultspec_rag/tests/ --collect-only -q -m <expr>` to size the population each selector reaches, without executing any test.
- Confirmed no CI workflow invokes pytest at all (checked `.github/workflows/`), so the local test recipe is the only gate that exists for this suite.
- Edited `_dev-test` in `justfile`: dropped `-x` from the default `python` target and changed its marker expression from `-m unit` to `-m "not integration"`.
- Added a new opt-in `fast` target on `_dev-test` that preserves the prior `-x -q --tb=short -m unit` behavior for quick local iteration; left it out of the `all`/`ci` chain so it is never the default gate.
- Verified the edited recipe bodies with `--collect-only` only (no full run), confirming the new default reaches the intended broader population and the new `fast` target still reaches the narrower one.

## Outcome

- `_dev-test python` (the default `just dev test` / `just ci` path) now runs `{{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "not integration"` — collects 2395/2986 tests (591 deselected), up from 1808/2986 (1178 deselected) under the prior `-m unit` expression, and no longer stops at the first failure.
- Root cause of the gap: registered markers `unit` (1808 collected) and `integration` (591 collected) together cover only 2399 of 2986 tests; roughly 587 tests carry neither marker and were silently dropped by `-m unit`, alongside small `cuda`/`subprocess_gpu`/`performance`/`quality`/`robustness`-only populations. `-m "not integration"` only excludes the 591 explicitly integration-marked tests, so it is the accurate "everything not integration" selector and matches the population the project's baseline health run this session actually measured.
- Judgement: fixed the recipe expression rather than backfilling the `unit` marker onto the ~587 unmarked tests. Marking every unmarked test function individually is a `src/vaultspec_rag/tests/` content change outside harness-ops scope (owned by code-authoring agents) and a materially larger, judgment-heavy change than a one-line recipe fix; team lead is tracking the marker gap itself as separate follow-up debt rather than folding a mass backfill into this plan at 92%+ completion.
- Added `_dev-test fast` (`-x -q --tb=short -m unit`, 1808/2986 collected, 1178 deselected) as a deliberate, explicitly opt-in fast-iteration escape hatch — not wired into `dev test all` or `ci`.
- No regression to the `--no-sync` fix landed earlier in this domain: every recipe invocation continues to route through the shared `{{uvr}}` runner variable, and no `uv` re-sync/rebuild was observed during verification.

## Notes

- Verification was `--collect-only` only; no full test execution (with or without `-x`) was run as part of this Step, per the assigning instruction to avoid re-running the full suite. The counts above are collection counts, not pass/fail counts.
- This Step's own finding — that `test_cli_search_safety.py::test_search_command_renders_numbered_results_from_http_response` fails under the corrected recipe — was traced separately (by another agent, read-only) to a stale test fixture (`tests/_cli_helpers.py:217` hardcoding the pre-canonicalization `"codebase"` value instead of the canonical `"code"`); that fix is tracked as its own Step and is out of scope here.
