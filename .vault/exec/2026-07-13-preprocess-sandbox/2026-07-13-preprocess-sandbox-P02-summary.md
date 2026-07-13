---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# `preprocess-sandbox` `P02` summary

All five Steps closed (S06-S10). Files touched:

- Created: `src/vaultspec_rag/indexer/_hook_sandbox.py`, `_hook_sandbox_windows.py`, `_hook_sandbox_posix.py`, `src/vaultspec_rag/tests/test_hook_sandbox.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_runner.py`, `src/vaultspec_rag/indexer/_preprocess_config.py`, `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Built the containment boundary (ADR D1-D6). A `HookSandbox` abstraction stages
the source into a per-run scratch dir, curates a secret-free child env, and
routes the single runner launch through a pluggable backend, fail-closed in
server mode. The Windows AppContainer backend (built and proven by the
orchestrator) denies the child filesystem access outside an ACL-granted staged
dir, denies network egress and loopback via zero capability SIDs, and is wrapped
in a kill-on-close Job Object; Linux bubblewrap and macOS seatbelt backends
cover the other platforms, with Landlock a documented fail-closed gap. The
runner stages, rewrites the hook argv to the staged copy, launches through the
backend, and remaps staged paths back to the real source so deep-link anchors
stay valid. Verification: the real AppContainer containment test passes on this
host (staged read allowed; secret read, network, and secret env all denied);
the worker import chain stays torch-free; ruff and basedpyright clean.
