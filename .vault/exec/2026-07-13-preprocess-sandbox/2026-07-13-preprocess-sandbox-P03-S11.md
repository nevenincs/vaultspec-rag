---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S11'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Make the watcher change filter recognize preprocessable files independent of the removed trust state

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Verify the watcher change filter no longer carries a residual trust gate after P01.
- Confirm the watcher resolves the root's preprocess config through the public accessor
  on the codebase indexer, which now delegates to the loader unconditionally.
- Add a regression test asserting a rule-matched file is recognized as a code change
  under the default mode with no trust record present.

## Outcome

No residual product bug: P01 already removed the trust branch from the loader, so the
loader's mode enforcement now applies only the `off` kill switch and returns a root's
resolved rules for any root. The watcher builds its filter config from the codebase
indexer's public preprocess accessor, which calls that loader directly with no trust
input, so a watched preprocessable file is recognized under the default mode. The change
filter itself was already preprocess-aware and needed no code change.

Added a regression test in `test_watcher_unit.py`. It writes a real
`.vaultragpreprocess.toml` with a `*.pdf` rule under an isolated status dir and the
on-sandbox default mode, resolves the config through the loader, and asserts the change
filter admits a watched `.pdf` when handed that config and rejects it when handed none -
proving the resolved rule is what admits the otherwise-unsupported extension. A new
fixture isolates the status dir and clears the two mode env vars so the resolved mode is
the default.

## Outcome verification

`ruff check`, `basedpyright`, and the watcher unit suite all pass; the new test is green.

## Notes

S11 found no residual bug in the watcher after P01; the step is a regression guard only,
as the task anticipated. No code change to `watcher.py` was required for the filter
itself (a separate one-line change to the code-reindex finish call was made under S12 to
thread preprocess failures, unrelated to the filter logic).
