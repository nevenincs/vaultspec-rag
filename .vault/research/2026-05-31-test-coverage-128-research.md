---
tags:
  - '#research'
  - '#test-coverage-128'
date: '2026-05-31'
related: []
---

# `test-coverage-128` research: `integration CI + tqdm purity + JSON purity`

## Trigger

End-of-Wave-2 honest audit. Three coverage gaps:

- **Gap 1 — integration on PRs.** The unit `Tests` job in `ci.yml`
  runs on every PR (`pull_request:` trigger). The
  `gpu-integration.yml` workflow that runs the integration marker
  only fires on `push` to `main` and `workflow_dispatch`. So none
  of PRs #112/#113/#114/#115 had integration verification before
  merge.
- **Gap 2 — tqdm purity.** `_suppress_hf_progress()` sets
  `HF_HUB_DISABLE_PROGRESS_BARS=1`, `TRANSFORMERS_NO_ADVISORY_WARNINGS=1`,
  and `TOKENIZERS_PARALLELISM=false`. CrossEncoder constructor sets
  `show_progress_bar=False`. There is no test that subprocesses a
  CLI invocation and asserts zero `\r` carriage-return characters
  in stdout (tqdm's rewrite signal).
- **Gap 3 — `--json` purity is one command deep.**
  `TestJsonOutputMode::test_envelope_is_pure_stdout_no_rich_bytes`
  covers `search` filter-mismatch (one error path). Other branches
  (`index --dry-run`, `status`, `server service status`, `server service projects list`) are not asserted to produce pure JSON on
  success.

## Method

Code-read against `main` after PR #134. Reviewed
`.github/workflows/{ci.yml,gpu-integration.yml}` to confirm trigger
gap. Audited existing `TestJsonOutputMode` test class
(`src/vaultspec_rag/tests/test_cli.py`) for coverage breadth.

## Findings

### CI integration trigger

`gpu-integration.yml` runs on a self-hosted `[self-hosted, gpu]`
runner with `HF_TOKEN` secret. Adding `pull_request:` with a
`branches: [main]` filter would make the integration suite gate
every PR before merge. Path filter is already in place on push;
mirror it on pull_request to avoid spinning up the GPU runner for
docs-only PRs.

External PRs (from forks) cannot access the `HF_TOKEN` secret, so
the job will skip or fail. Acceptable: this repo is solo-maintained
and external contributions are rare. Document the constraint in
the workflow comment.

### tqdm purity subprocess test

The cleanest subject is `vaultspec-rag --help` because it does not
require GPU, does not touch the index, and does not load models —
yet it imports the whole package, which is where stray tqdm import
side-effects would surface.

`--help` doesn't exercise the encode path though, so it doesn't
prove the encode-time suppression works. The encode path requires
GPU + corpus. Compromise: assert `_suppress_hf_progress()` sets
the right env vars (deterministic, no subprocess needed). The
subprocess test focuses on import-time leakage with
`vaultspec-rag --help`.

Real encode-time purity belongs in the integration suite where GPU
is available; add `TestEncodeStdoutPurity::test_search_stdout_has_no_tqdm`
as an integration test that runs `vaultspec-rag search "x" --type code --max-results 1` via subprocess and grep stdout for `\r`.

### `--json` exhaustive purity

Parametric test enumerating the commands that support `--json`:

- `search "x" --type code --json` (failure path: no index)
- `index --dry-run --json`
- `status --json`
- `server service status --json` (no daemon required — the command
  surfaces "not running" envelope)

Each invocation: subprocess, capture stdout, assert
`stdout.strip()` is parseable JSON, assert no ANSI escape
sequences (`\x1b[`) or box-drawing characters (`─│└┌╭╮`) are
present.

## Recommendation

One PR:

1. **`gpu-integration.yml`**: add `pull_request:` trigger with the
   same path filter; add explanatory comment about secret-access
   constraints for fork PRs.
1. **`test_cli.py::TestTqdmSuppression`**: subprocess
   `vaultspec-rag --help`, assert no `\r` in stdout. Plus a unit
   that calls `_suppress_hf_progress()` and verifies the env vars.
1. **`test_cli.py::TestJsonOutputMode`**: parametric test across
   the four commands above. Assert JSON parse + no Rich/ANSI
   characters.

No exception-suppression introduced; no shims; one cohesive change.
