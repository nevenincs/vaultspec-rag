---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:1ea24e509a79738f5c1973652156c4f618cf782470e7ac25d715fa37c5deaea7'
step_id: 'S03'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Retire trust_all, add VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED, and resolve the amended preprocess_mode (on-sandboxed default, off, unsandboxed)

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Retire `trust_all` from the `PreprocessMode` literal and the valid-mode set, replacing it with `unsandboxed`; the tri-state is now `default` / `off` / `unsandboxed`.
- Remove the `PREPROCESS_TRUST_ALL` env member and add `PREPROCESS_UNSANDBOXED` mapped to `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED`.
- Rewrite the `preprocess_mode` property so `VAULTSPEC_RAG_PREPROCESS=off` wins, a truthy `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED` resolves `unsandboxed`, else the configured/default value; keep the unrecognised-value degradation to `default`.
- Update the default-mode comment to describe on-sandbox default and the dangerous unsandboxed escape hatch.

## Outcome

The config vocabulary matches the sandbox model: `default` runs rules under the sandbox, `off` is the kill switch, and `unsandboxed` opts a backend-less host into running hooks without containment (stored and resolved now, consumed by the sandbox workstream later). Basedpyright and ruff are clean.

## Notes

`unsandboxed` currently resolves and is stored but is not yet acted on; the runner-side sandbox workstream consumes it.
