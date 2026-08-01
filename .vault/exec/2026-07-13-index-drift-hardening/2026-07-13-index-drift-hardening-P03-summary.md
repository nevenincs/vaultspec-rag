---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:6532f66b1699c2ba45a360938c23c9c2febb7560f8deee95e0dc59e1c08efcbd'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# `index-drift-hardening` `P03` summary

All three Steps closed (S09-S11). Files touched across the Phase:

- Modified: `src/vaultspec_rag/cli/_preprocess.py`
- Modified: `src/vaultspec_rag/cli/_service_lifecycle.py`
- Modified: `src/vaultspec_rag/cli/_process.py`
- Modified: `src/vaultspec_rag/cli/_index.py`
- Modified: `src/vaultspec_rag/tests/test_cli_preprocess.py`

## Description

Exposed the tri-state and trust flow through the CLI (ADR D7-D8). The
preprocess group gained `trust` (prints the resolved command set, confirms
interactively or via `--yes`, persists the record with a CLI-computed UTC
timestamp; `--json` requires `--yes`; refuses an empty or invalid config),
`untrust` (reports whether a record existed), and `status` (mode, config
presence, rule count, hash, and trust state, human and JSON). `run-one` now
distinguishes a genuine non-match from a rule set the trust gate hid and names
the trust verb. `server start` and `index` gained mutually-exclusive
`--no-preprocess` / `--preprocess-trust-all` flags: server start forwards the
mode into the daemon env exactly like the local-only precedent and prints an
actionable notice when the target root's config is untrusted; the index verb
sets the env in-process for local runs and warns loudly that a delegated run
keeps the daemon's start-time mode. Trust verbs use the strict loader
deliberately - they must review rules the gate would hide - while every
executing path stays behind the non-strict gate.

Verification: 39 CLI tests pass covering the confirm/decline/auto-accept
flows, refusal on empty config, the JSON envelopes, gated-versus-trusted
run-one messaging, flag mutual exclusion, the daemon-env forwarding matrix,
and the in-process env application; 161 adjacent index/CLI tests stay green;
ruff and basedpyright report zero findings on the CLI surface. The
orchestrator fixed one test-isolation defect found in the full-suite gate: the
in-process env mutation the index flags perform by design leaked across test
modules, so the module fixture now snapshots and force-restores both mode
keys.
