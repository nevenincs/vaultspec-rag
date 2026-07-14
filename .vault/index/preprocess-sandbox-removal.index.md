---
generated: true
tags:
  - '#index'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S01]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S02]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S03]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S04]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S05]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S06]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-S07]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P01-summary]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S08]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S09]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S10]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S11]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S12]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S13]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-S14]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P02-summary]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S15]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S16]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S17]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S18]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S19]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-S20]]'
  - '[[2026-07-14-preprocess-sandbox-removal-P03-summary]]'
  - '[[2026-07-14-preprocess-sandbox-removal-adr]]'
  - '[[2026-07-14-preprocess-sandbox-removal-plan]]'
---

# `preprocess-sandbox-removal` feature index

Auto-generated index of all documents tagged with `#preprocess-sandbox-removal`.

## Documents

### adr

- `2026-07-14-preprocess-sandbox-removal-adr` - `preprocess-sandbox-removal` adr: `Direct hook execution replaces OS containment: performance is the mandate` | (**status:** `accepted`)

### exec

- `2026-07-14-preprocess-sandbox-removal-P01-S01` - Rewrite the sandbox module to a direct-launch helper: keep curated_child_env and default_popen_handle, delete resolve_hook_sandbox, _probe_backend, stage_source, SandboxUnavailableError, and the HookSandbox protocol
- `2026-07-14-preprocess-sandbox-removal-P01-S02` - Delete the Windows AppContainer backend module (profile derivation, icacls grants, Job Object wrap, pipe plumbing)
- `2026-07-14-preprocess-sandbox-removal-P01-S03` - Delete the POSIX bwrap/seatbelt backend module
- `2026-07-14-preprocess-sandbox-removal-P01-S04` - Rewire run_preprocessor to launch the hook directly against the original source path with a fresh scratch cwd, dropping backend resolution/memos, staging, _remap_staged_paths, the _REFUSED_REASON policy, and the server_mode/unsandboxed parameters while keeping timeout, stdout/stderr caps, schema validation, the emitted cap, on_error dispositions, and argv hygiene
- `2026-07-14-preprocess-sandbox-removal-P01-S05` - Drop the server_mode/unsandboxed threading from preprocess_file and its callers, keeping the cache consult/write path unchanged
- `2026-07-14-preprocess-sandbox-removal-P01-S06` - Drop the sandbox-policy fields from the preprocess context construction and any backend mentions
- `2026-07-14-preprocess-sandbox-removal-P01-S07` - Update _resolve_preprocess_context to the two-state mode (no server_mode/unsandboxed plumbing)
- `2026-07-14-preprocess-sandbox-removal-P01-summary` - `preprocess-sandbox-removal` `P01` summary
- `2026-07-14-preprocess-sandbox-removal-P02-S08` - Collapse PreprocessMode to a two-state on/off by removing the unsandboxed literal, the PREPROCESS_UNSANDBOXED EnvVar, and the unsandboxed arm of the preprocess_mode property, keeping PREPROCESS=off as the kill switch
- `2026-07-14-preprocess-sandbox-removal-P02-S09` - Remove the --preprocess-unsandboxed flag and its mutual-exclusion validation from the index command
- `2026-07-14-preprocess-sandbox-removal-P02-S10` - Remove the --preprocess-unsandboxed flag and env forwarding from server start, keeping --no-preprocess
- `2026-07-14-preprocess-sandbox-removal-P02-S11` - Update the preprocess status verb to report direct execution and the two-state mode instead of the resolved sandbox backend
- `2026-07-14-preprocess-sandbox-removal-P02-S12` - Drop UNSANDBOXED from the daemon child-env forwarding allow-list
- `2026-07-14-preprocess-sandbox-removal-P02-S13` - Remove sandbox-state fields from job records and the /jobs and preprocess reporting surfaces
- `2026-07-14-preprocess-sandbox-removal-P02-S14` - Remove sandbox-backend reporting from the server routes preprocess pre-flight
- `2026-07-14-preprocess-sandbox-removal-P02-summary` - `preprocess-sandbox-removal` `P02` summary
- `2026-07-14-preprocess-sandbox-removal-P03-S15` - Replace the OS-containment test suite with direct-launch tests covering curated env, scratch cwd, timeout kill, and cap enforcement
- `2026-07-14-preprocess-sandbox-removal-P03-S16` - Update runner tests: drop backend/staging/refusal cases, assert original-path invocation and preserved bounds/dispositions
- `2026-07-14-preprocess-sandbox-removal-P03-S17` - Update worker, config, entry, CLI, server, watcher, and integration tests for the two-state mode and removed flags
- `2026-07-14-preprocess-sandbox-removal-P03-S18` - Update operator docs to the trust-based framing that preprocess config is code execution with operator privileges, removing sandbox/unsandboxed knob references
- `2026-07-14-preprocess-sandbox-removal-P03-S19` - Sweep remaining sandbox mentions from README, cli, and configuration docs
- `2026-07-14-preprocess-sandbox-removal-P03-S20` - Run the full unit suite, lints (ruff, ty, basedpyright), and an end-to-end preprocess index benchmark on a rule-matched corpus to confirm the per-file cost returns to the process-spawn baseline
- `2026-07-14-preprocess-sandbox-removal-P03-summary` - `preprocess-sandbox-removal` `P03` summary

### plan

- `2026-07-14-preprocess-sandbox-removal-plan` - `preprocess-sandbox-removal` plan
