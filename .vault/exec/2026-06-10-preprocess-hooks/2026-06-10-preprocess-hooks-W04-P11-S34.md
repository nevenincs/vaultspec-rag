---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S34'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add the html_strip config default and env override (D13)

## Scope

- `src/vaultspec_rag/config.py`

## Description

Added the `html_strip` config knob (default `True`) following the `_RAG_DEFAULTS` +
`_ENV_OVERRIDE_MAP` convention: EnvVar `VAULTSPEC_RAG_HTML_STRIP`, default-bool coercion via
the existing `_resolve_rag_default` path (D13).

## Outcome

Operators can disable HTML stripping with `VAULTSPEC_RAG_HTML_STRIP=0`; default keeps it on.

## Notes

Env-only override (no CLI flag), so the spawn worker resolves the same value the parent
would.
