---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S13'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Add the /reindex pre-flight signal reporting whether a root ships a preprocess config and whether hooks will run under the resolved sandbox

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Add a torch-free pre-flight helper to the routes module that resolves a root's
  preprocess config and reports whether hooks will run under the current mode.
- Mirror the shape of the existing `server start` operator notice, but as JSON fields
  rather than a printed line.
- Embed the pre-flight object under a `preprocess` key in the reindex response without
  changing the queuing behavior.
- Add the `Path` type to the module's type-checking imports for the helper signature.
- Cover the response with route-level tests across the default, off, and no-config cases.

## Description verification

The reindex response now carries a `preprocess` object with `config_present` (whether the
root ships a `.vaultragpreprocess.toml`), `rule_count` (the config's own resolved rule
count, reported regardless of mode), `mode` (the resolved tri-state), and
`hooks_will_run` (true only when a config with rules is present and the mode is not the
`off` kill switch). The rule count is resolved in strict mode so the kill switch does not
mask the config's true size. The helper uses the CPU-only rule loader and the config
accessor, so the routes layer stays off the torch import path. Queuing is unchanged: the
job still starts and the route still returns `queued`; the pre-flight only enriches the
response.

## Outcome

A non-interactive client calling reindex learns before indexing runs whether the root's
hooks will fire, closing the last of the three server-path visibility gaps.

## Outcome verification

`ruff check`, `basedpyright`, and the server unit suite all pass. Three new route tests
drive the real route through the test client with the GPU-backed job start and the
watcher nudge isolated, asserting the pre-flight fields for a config-bearing root under
the default and off modes and for a root with no config; the pre-flight resolution itself
runs against a real config file and is not stubbed.

## Notes

None.
