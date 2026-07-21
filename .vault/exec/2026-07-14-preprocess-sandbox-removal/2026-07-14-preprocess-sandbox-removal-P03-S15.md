---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S15'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Replace the OS-containment test suite with direct-launch tests covering curated env, scratch cwd, timeout kill, and cap enforcement

## Scope

- `src/vaultspec_rag/tests/test_hook_sandbox.py`

## Description

- Replace the OS-containment suite with direct-launch tests using real child processes: `curated_child_env` allow-list strictness (drops `VAULTSPEC_RAG_*` and credential-shaped vars, keeps the allow-list); a real child confirms the secret is absent and `PATH` present; `default_popen_handle` honours cwd/env and captures both pipes.

## Outcome

All AppContainer/bwrap/probe/fail-closed/staging tests deleted; new suite green with no mocks.

## Notes

Executed by the dispatched high-executor; supervisor verified results.
