---
tags:
  - '#plan'
  - '#test-coverage-128'
date: '2026-05-31'
modified: '2026-06-30'
related:
  - '[[2026-05-31-test-coverage-128-adr]]'
  - '[[2026-05-31-test-coverage-128-research]]'
---

# `test-coverage-128` plan: `integration on PRs + tqdm purity + JSON purity`

Implements gh #128 in one PR.

## Tasks

### Phase 1 — CI

- Add `pull_request:` trigger to `.github/workflows/gpu-integration.yml`
  with the same path filter as `push:`. Add comment about
  `secrets.HF_TOKEN` access for fork PRs.

### Phase 2 — tqdm purity tests

- New class `TestTqdmSuppression` in
  `src/vaultspec_rag/tests/test_cli.py`:
  - `test_suppress_hf_progress_sets_env_vars`: invoke
    `_suppress_hf_progress()`, assert env vars.
  - `test_help_subprocess_stdout_has_no_cr`: subprocess
    `[sys.executable, "-m", "vaultspec_rag", "--help"]`, assert
    exit 0, assert no `b"\r"` in stdout.

### Phase 3 — JSON purity

- New parametric test
  `TestJsonOutputMode::test_envelope_is_pure_json_across_commands`:
  pytest.mark.parametrize over four (name, argv) tuples. For each:
  subprocess, parse JSON, assert no ANSI / box-drawing in stdout.

### Phase 4 — verification

- `uv run --no-sync ruff check src/` clean.
- `uv run --no-sync ruff format src/` clean.
- `uv run --no-sync ty check src/vaultspec_rag/tests/test_cli.py`.
- `uv run --no-sync pytest src/vaultspec_rag/tests/test_cli.py -k "Tqdm or JsonOutputMode" -q`.

### Phase 5 — commit + push + PR + merge

- One commit: vault docs + workflow + tests.
- PR title `test(ci): integration on PRs + tqdm/JSON stdout purity (#128)`.
- Squash-merge once CI green.

## Verification

- Workflow Lint passes (actionlint).
- All four new tests pass.
- No new `except` clauses.

## Out of scope

- Encode-time tqdm purity: covered by future integration-tier
  test once #128 CI gate is live.
- Replacing Rich with a non-tty-aware renderer.
- Removing the GPU-on-PR cost concern via a separate marker run
  on a cheaper runner.
