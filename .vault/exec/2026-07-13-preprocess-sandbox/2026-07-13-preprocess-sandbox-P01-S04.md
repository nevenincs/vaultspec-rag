---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S04'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Drop the trust and untrust verbs, repoint preprocess status at sandbox-backend availability, keep --no-preprocess and add the unsandboxed flag

## Scope

- `src/vaultspec_rag/cli/_preprocess.py`

## Description

- Delete the `trust` and `untrust` command functions and their helpers (`_print_command_set`, `_resolved_command_set`, `_trust_state`, `_status_effect_line`'s trust branches, `_invocation_label`) from the preprocess CLI, and drop the trust-store imports.
- Repoint `status` to report mode, config presence, config validity, rule count, a `would_run` flag (true unless `off`), and a sandbox-backend line; the backend reads a module-level placeholder (`not yet wired`) since the sibling `_hook_sandbox` module does not exist yet.
- Simplify `run-one` gating to the `off` case only (the sole remaining loader gate) and rewrite its gated message accordingly.
- Rename the `--preprocess-trust-all` flag to `--preprocess-unsandboxed` across `server start` and `index`, keeping the mutual exclusion with `--no-preprocess`, and repoint all forwarding (`cli/_index.py`, `cli/_service_lifecycle.py`, `cli/_process.py`) onto `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED` and the `unsandboxed` literal.

## Outcome

The operator surface no longer offers per-root consent: `status`/`list`/`check`/`run-one` work without any trust store, the renamed unsandboxed flag forwards the new env var through both the in-process and daemon paths, and the start-time notice reports sandbox/off/unsandboxed instead of trust state. Basedpyright and ruff are clean across all five touched files.

## Notes

The sandbox-backend line is a deliberate placeholder constant. When the sibling workstream lands `_hook_sandbox`, `_sandbox_backend()` should be extended to report the real resolved backend rather than the `not yet wired` string; no fake backend is invented in the interim.
