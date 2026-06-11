---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S41'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Update the README with the feature, new env vars, and CLI verbs (D13)

## Scope

- `README.md`

## Description

Linked the new guide from the README "Daily use" section and added the two new env vars
(`VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`, `VAULTSPEC_RAG_HTML_STRIP`) to
`docs/configuration.md` with a pointer to the hooks guide (D13).

## Outcome

The feature is discoverable from the README and the env vars are in the canonical config
reference.

## Notes

CLAUDE.md's vaultspec-rag rule is a generated `.builtin.md` mirror (sourced upstream in
vaultspec-core) and is intentionally not hand-edited here.
