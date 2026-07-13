---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S10'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Unit-test the sandbox contract and each backend: staged-only filesystem read, denied network, denied secret env, process-tree teardown, and the fail-closed refusal when no backend resolves

## Scope

- `src/vaultspec_rag/tests/test_hook_sandbox.py`

## Description

- Add a no-GPU unit module for the hook sandbox with a shared probe child that,
  from inside containment, reads its staged file, attempts to read a secret file
  staged outside the grant, attempts a TCP connect, and reports the daemon secret
  it sees in its environment - returning a JSON verdict.
- Assert `curated_child_env` drops every `VAULTSPEC_RAG_*`, `HF_`, Qdrant, and
  token variable while keeping `PATH`, and that no secret value survives.
- Assert the resolve policy: server mode with no backend raises
  `SandboxUnavailableError`; the unsandboxed opt-in returns `None` without
  probing; local mode with no backend returns `None`.
- Launch a real AppContainer child on Windows via the genuine backend (no
  mocks), granting only the scratch dir and the base interpreter prefix, and
  assert the child read its staged file, was denied the outside secret, was
  denied the network, and never saw the API key.
- Add the platform-matched bubblewrap real-containment test, gated by platform
  and `bwrap` availability.

## Outcome

The real AppContainer launch on this Windows host confirmed containment end to
end: `staged_read == "ok"`, `secret_read` denied, `network` denied, and
`api_key_present is False`. Suite result: 5 passed, 1 skipped (the Linux
bubblewrap test, correctly gated off on Windows). Lint and type checks pass.

## Notes

The AppContainer test launches the base interpreter with only the base prefix
granted (not the full venv), because the probe imports stdlib only; this keeps
the real `icacls` grant scoped and the test fast (~5s) while still proving the
containment boundary. The `skipif` gates are platform-capability gates for
OS-specific backends, not test-quality skips; no mocks of any backend are used.
