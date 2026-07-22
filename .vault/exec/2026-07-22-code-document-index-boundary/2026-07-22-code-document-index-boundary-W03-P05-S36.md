---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S36'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify options, versions, source binding, metadata retention, and path-dependent cache behavior with real extractor processes

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Exercise version, options, source binding, path behavior, metadata bounds, command execution, and entry-point execution.

## Outcome

The preprocessing phase boundary passed real subprocess, cache, configuration, schema,
batch, and CLI behavior. Dedicated integration checks now cover option propagation,
extractor-version invalidation, source binding, metadata retention, path isolation, cap
invalidation, and structured policy failures.

## Notes

The remediation gate passed seven dedicated real-behavior checks and the broader focused
preprocess gate passed 99 checks. The module collects fourteen integration checks.
