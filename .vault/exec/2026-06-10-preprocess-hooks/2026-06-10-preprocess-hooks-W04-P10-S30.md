---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:0903ea62abc0860eff806d553a3068daff8be72f5650051a562f66d3452ad054'
step_id: 'S30'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for the three verbs including check non-zero exit on invalid config (D13)

## Scope

- `src/vaultspec_rag/tests/test_cli_preprocess.py`

## Description

Added `test_cli_preprocess.py` (7 tests) driving the verbs via Typer's `CliRunner` over a
real tmp workspace, a real `.vaultragpreprocess.toml`, and a real extractor script:
list-empty, list-shows-rule, check-valid (exit 0), check-invalid-toml (exit 1),
check-invalid-rule (exit 1), run-one-no-match, and run-one-matches-and-runs (status ok,
1 unit) (D13).

## Outcome

7/7 pass. Confirms `check` is the non-zero-exit hard-fail path and the `--json` envelope
shape.

## Notes

TOML command uses a triple-single-quoted literal so Windows backslash paths don't trip
TOML escape parsing - a real authoring gotcha worth noting in docs.
