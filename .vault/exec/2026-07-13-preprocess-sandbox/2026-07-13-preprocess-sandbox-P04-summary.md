---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
body_hash: 'sha256:6dff1644b787260d8cd39e6ee998fe0fd9348ca240839bf451ad9d1d677bbb4e'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# `preprocess-sandbox` `P04` summary

All two Steps closed (S14-S15). Files touched:

- Modified: `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`, `README.md`, `docs/preprocessing-hooks.md`, `docs/configuration.md`, `docs/cli.md`

## Description

Proved the model end-to-end and documented it (ADR D10). The integration test
was cleared of the deleted trust surface and gained three real GPU+Qdrant
proofs: a hook runs contained through a local index with no scratch-path leak in
its anchors; an untrusted repo's hook runs with NO trust step and is contained
(a secret outside the granted root and a network connect both denied while the
legitimate content still indexes); and the `off` kill switch skips hooks
entirely. Ten integration tests pass with the service stopped, the AppContainer
proof running in 61s. The docs across the README and three references were
rewritten to the containment model with every trust-era reference removed
(grep-confirmed). Verification: 10 integration tests pass; markdown hooks pass.
