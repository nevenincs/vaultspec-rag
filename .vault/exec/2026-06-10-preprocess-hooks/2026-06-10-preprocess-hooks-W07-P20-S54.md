---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S54'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Use a per-process cache temp-file suffix and read/validate the top-level config version field (PREPROCESS-006, CONFIG-001)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_cache.py`

## Description

Two tidies: the cache write now uses a per-process temp suffix (`.<pid>.tmp`) so two
workers processing byte-identical sources never collide on one temp file (PREPROCESS-006);
and the loader reads/validates the top-level config `version`, rejecting a config whose
version exceeds `SUPPORTED_CONFIG_VERSION` (degrade in default mode, raise in strict) so a
future incompatible config shape is never silently half-read (CONFIG-001).

## Outcome

Both shipped with unit coverage (`test_newer_config_version_degrades`,
`test_newer_config_version_strict_raises`); the temp-suffix change is covered by the
existing cache round-trip tests.

## Notes

`SUPPORTED_CONFIG_VERSION = 1`; the field was previously parsed-but-ignored.
