---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
body_hash: 'sha256:b4fd5b701d17923906cc11e7b46c6eab17329c1d30ce51baa7037a23d0c88b97'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# `preprocess-sandbox` `P01` summary

All five Steps closed (S01-S05). Files touched:

- Deleted: `src/vaultspec_rag/indexer/_preprocess_trust.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_config.py`, `src/vaultspec_rag/config.py`, `src/vaultspec_rag/cli/_preprocess.py`, `src/vaultspec_rag/cli/_index.py`, `src/vaultspec_rag/cli/_service_lifecycle.py`, `src/vaultspec_rag/cli/_process.py`, `src/vaultspec_rag/tests/test_preprocess_config.py`, `src/vaultspec_rag/tests/test_cli_preprocess.py`

## Description

Removed the trust-on-first-use surface shipped hours earlier (ADR D7-D8). The
trust store, the `preprocess trust`/`untrust` verbs, and the loader's trust
branch are gone; `load_preprocess_rules` now resolves a root's rules for any
root, gated only by the `off` kill switch, because containment - not consent -
becomes the boundary. The tri-state is `default` (on) / `off` / `unsandboxed`,
resolved live from `VAULTSPEC_RAG_PREPROCESS` and the renamed
`VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED`; the CLI flag became
`--preprocess-unsandboxed`. Verification: 54 unit tests pass; ruff and
basedpyright clean. This directly removes the silent-no-op that left
non-interactive server clients' hooks never running.
