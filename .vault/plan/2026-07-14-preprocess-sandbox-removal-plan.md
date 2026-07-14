---
tags:
  - '#plan'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
tier: L2
related:
  - '[[2026-07-14-preprocess-sandbox-removal-adr]]'
  - '[[2026-07-13-preprocess-sandbox-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `preprocess-sandbox-removal` plan

### Phase `P01` - Core sandbox removal

Delete the OS containment layer (backends, probe, staging, fail-closed policy) and rewire the runner to a direct bounded subprocess launch, per ADR D1-D3, D5, D7-D8.

- [x] `P01.S01` - Rewrite the sandbox module to a direct-launch helper: keep curated_child_env and default_popen_handle, delete resolve_hook_sandbox, _probe_backend, stage_source, SandboxUnavailableError, and the HookSandbox protocol; `src/vaultspec_rag/indexer/_hook_sandbox.py`.
- [x] `P01.S02` - Delete the Windows AppContainer backend module (profile derivation, icacls grants, Job Object wrap, pipe plumbing); `src/vaultspec_rag/indexer/_hook_sandbox_windows.py`.
- [x] `P01.S03` - Delete the POSIX bwrap/seatbelt backend module; `src/vaultspec_rag/indexer/_hook_sandbox_posix.py`.
- [x] `P01.S04` - Rewire run_preprocessor to launch the hook directly against the original source path with a fresh scratch cwd, dropping backend resolution/memos, staging, _remap_staged_paths, the _REFUSED_REASON policy, and the server_mode/unsandboxed parameters while keeping timeout, stdout/stderr caps, schema validation, the emitted cap, on_error dispositions, and argv hygiene; `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `P01.S05` - Drop the server_mode/unsandboxed threading from preprocess_file and its callers, keeping the cache consult/write path unchanged; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P01.S06` - Drop the sandbox-policy fields from the preprocess context construction and any backend mentions; `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `P01.S07` - Update _resolve_preprocess_context to the two-state mode (no server_mode/unsandboxed plumbing); `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - Control-surface collapse

Collapse the preprocess tri-state to on/off, remove the UNSANDBOXED env knob and CLI flags, and update every adapter that reports or forwards sandbox state, per ADR D4 and D10.

- [x] `P02.S08` - Collapse PreprocessMode to a two-state on/off by removing the unsandboxed literal, the PREPROCESS_UNSANDBOXED EnvVar, and the unsandboxed arm of the preprocess_mode property, keeping PREPROCESS=off as the kill switch; `src/vaultspec_rag/config.py`.
- [x] `P02.S09` - Remove the --preprocess-unsandboxed flag and its mutual-exclusion validation from the index command; `src/vaultspec_rag/cli/_index.py`.
- [x] `P02.S10` - Remove the --preprocess-unsandboxed flag and env forwarding from server start, keeping --no-preprocess; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P02.S11` - Update the preprocess status verb to report direct execution and the two-state mode instead of the resolved sandbox backend; `src/vaultspec_rag/cli/_preprocess.py`.
- [x] `P02.S12` - Drop UNSANDBOXED from the daemon child-env forwarding allow-list; `src/vaultspec_rag/cli/_process.py`.
- [x] `P02.S13` - Remove sandbox-state fields from job records and the /jobs and preprocess reporting surfaces; `src/vaultspec_rag/jobs.py`.
- [x] `P02.S14` - Remove sandbox-backend reporting from the server routes preprocess pre-flight; `src/vaultspec_rag/server/_routes.py`.

### Phase `P03` - Tests, docs, and verification

Rewrite the test surface for direct execution semantics, update operator docs to the trust-based framing, and verify the full suite plus an end-to-end preprocess index run, per ADR D6 and D9.

- [ ] `P03.S15` - Replace the OS-containment test suite with direct-launch tests covering curated env, scratch cwd, timeout kill, and cap enforcement; `src/vaultspec_rag/tests/test_hook_sandbox.py`.
- [ ] `P03.S16` - Update runner tests: drop backend/staging/refusal cases, assert original-path invocation and preserved bounds/dispositions; `src/vaultspec_rag/tests/test_preprocess_runner.py`.
- [ ] `P03.S17` - Update worker, config, entry, CLI, server, watcher, and integration tests for the two-state mode and removed flags; `src/vaultspec_rag/tests/`.
- [x] `P03.S18` - Update operator docs to the trust-based framing that preprocess config is code execution with operator privileges, removing sandbox/unsandboxed knob references; `docs/preprocessing-hooks.md`.
- [x] `P03.S19` - Sweep remaining sandbox mentions from README, cli, and configuration docs; `docs/`.
- [ ] `P03.S20` - Run the full unit suite, lints (ruff, ty, basedpyright), and an end-to-end preprocess index benchmark on a rule-matched corpus to confirm the per-file cost returns to the process-spawn baseline; `src/vaultspec_rag/`.

## Description

Remove the OS-level preprocess hook sandbox per the accepted removal ADR (D1-D10 in the
related frontmatter chain). The AppContainer/bwrap/seatbelt containment layer costs
~5-8s per matched file against a ~50ms baseline (measured: 640 chunks in 80 minutes on
the aeat corpus); the owner mandate keeps preprocessing on by default and removes the
containment. The hook remains a bounded subprocess grandchild (CPU/CUDA-correctness
boundary per the preprocess-hooks ADR D6/D9 and the index-workers-stay-cpu-only rule)
with the curated env, timeout, output caps, schema validation, and content-hash cache
all retained. The tri-state control surface collapses to on/off (BREAKING: the
UNSANDBOXED env knob and --preprocess-unsandboxed flags are removed).

## Steps

## Parallelization

P01 lands first: it defines the new runner/launch surface everything else compiles
against. Within P01, S01-S03 (module rewrite and deletions) precede S04-S07. P02 steps
are mutually independent once P01 lands and may proceed in any order or in parallel.
P03 runs last; within it S15-S17 (tests) can parallelize, S18-S19 (docs) can
parallelize with the tests, and S20 (full verification) is strictly final.

## Verification

- The full unit suite passes with the sandbox modules deleted; no test imports
  `_hook_sandbox_windows` or `_hook_sandbox_posix`.
- `rg -i "unsandboxed|appcontainer|bwrap|sandbox-exec"` over `src/` returns no
  production hits (test/docs mentions only where historically framed).
- Lints and type checks pass: ruff, ty, basedpyright.
- A rule-matched corpus indexes with per-file hook cost at process-spawn baseline
  (no icacls children, no AppContainer launches in Process Monitor terms); the 80-minute
  aeat pathology is not reproducible.
- The fresh-interpreter regression guard still shows `torch` absent from
  `sys.modules` after importing the chunk worker (index-workers-stay-cpu-only holds).
- `vaultspec-rag preprocess status` reports the two-state mode; `--preprocess-unsandboxed`
  is rejected as an unknown flag by `index` and `server start`.
