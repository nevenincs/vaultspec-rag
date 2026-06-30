---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S07'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add the preprocess_max_emitted_bytes config knob and enforce the emitted-text cap in the runner (D10)

## Scope

- `src/vaultspec_rag/config.py`

## Description

Added the `preprocess_max_emitted_bytes` knob to `config.py` (EnvVar
`VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`, `_ENV_OVERRIDE_MAP` entry, default 10 MiB)
following the existing `_RAG_DEFAULTS` convention. The runner enforces it against the total
emitted text length (sum of unit texts, or len(text)), separate from `_MAX_FILE_SIZE` which
bounds source size (D10).

## Outcome

Knob wired and consumed by the runner; basedpyright zero. Default mirrors `_MAX_FILE_SIZE`
but is independently tunable.

## Notes

The cap is the emitted-text axis from the ADR; the source-size relaxation lands in W03.P06.
