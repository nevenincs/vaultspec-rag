---
tags:
  - '#plan'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-19'
tier: L2
related:
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-07-14-tool-env-gpu-continuity-research]]'
---

# `tool-env-gpu-continuity` plan

### Phase `P01` - Env classification and exact-command remediation

Give every GPU-refusal surface an environment-aware, copy-paste remediation: classify the runtime env (installed-tool, uvx-ephemeral, project-venv, other), derive the escape-hatch and durable receipt-install command strings from one constant surface, and rewrite the CPU-wheel refusal and installer warning to emit them (ADR A/B/C).

- [x] `P01.S01` - Add a pure-path runtime env classifier (installed-tool, uvx-ephemeral, project-venv, other) keyed on sys.prefix vs UV_TOOL_DIR and UV_CACHE_DIR shapes including archive-v0, with \_running_in_uv_tool_env delegating to it, plus a single constant-derived helper producing the escape-hatch command for a given interpreter and the durable receipt-carrying uv tool install command; `src/vaultspec_rag/cli/_gpu_errors.py`.
- [x] `P01.S02` - Rewrite the CPU-only messaging in warn_if_active_torch_not_gpu to emit the immediate escape hatch plus the durable receipt fix selected by env classification, sourcing both strings from the new helper; `src/vaultspec_rag/cli/_gpu_errors.py`.
- [x] `P01.S03` - Extend the \_preflight_daemon_cuda refusal to print the env classification label beside the Service interpreter path and the exact escape-hatch plus durable-fix commands for the resolved interpreter, dropping the vaultspec-rag install next-action on non-project envs; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S04` - Add a prominent uvx-ephemeral warning to server start, as human text plus a warnings field inside the json success envelope (never stray text), naming the installed-tool path and the stop-the-service-before-forced-reinstall guidance; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S05` - Add classifier truth-table tests (tools dir, archive-v0 cache, project venv, env-var overrides, Windows path shapes), refusal-message content tests, and a single-source test asserting the remediation strings derive from the cu130 constants; `src/vaultspec_rag/tests/test_service_env_preflight.py`.

### Phase `P02` - Warming status state

Close the lock-held-but-not-serving gap: the daemon stamps a warming-then-running phase into the status sidecar and status rendering gains a distinct warming state with back-compat for absent phase (ADR D).

- [x] `P02.S06` - Add an optional phase field to the service status sidecar schema with writer and reader back-compat treating an absent phase as today's semantics; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `P02.S07` - Stamp phase warming into the status sidecar after machine-lock acquisition and before component warmup, and phase running at the lifespan yield, written by the daemon process only; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P02.S08` - Add a warming branch to \_explicit_port_state and the port-only renderer (pid and since rendering, distinct exit code) and make the already-owns-this-machine start message say warming when the sidecar phase says so; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P02.S09` - Add status-state fixtures asserting warming rendering, the distinct exit code, and absent-phase back-compat alongside the existing stopped and unreachable cases; `src/vaultspec_rag/tests/test_cli.py`.

### Phase `P03` - Jobs signposting and documentation

Signpost server jobs --json in the human summary and help, and document the canonical receipt-carrying tool install command, the upgrade contract, and the ephemeral-env trap (ADR E and A docs).

- [x] `P03.S10` - Mention --json in the human jobs summary line and command help so scripted consumers are routed to the structured envelope instead of grepping the word active; `src/vaultspec_rag/cli/_service_jobs.py`.
- [x] `P03.S11` - Assert the jobs human summary carries the --json signpost and that the jobs --json envelope shape is unchanged; `src/vaultspec_rag/tests/test_jobs_unit.py`.
- [x] `P03.S12` - Document the canonical receipt-carrying tool install command with the upgrade contract, the --with wheel-URL fallback, and the ephemeral-env trap including stop-the-service-before-forced-reinstall; `README.md`.

### Phase `P04` - Verification

Full-suite and on-box verification, including the execution-phase gate on the uv --index behaviour for uv tool installs on Windows and the manual persona pass mandated for CLI operability changes.

- [ ] `P04.S13` - Run the full unit and integration suites with the machine service stopped and isolated status and storage dirs, fixing any regressions the new surfaces introduce; `src/vaultspec_rag/tests`.
- [ ] `P04.S14` - Execute the on-box manual persona pass on the GPU machine: install via the receipt-carrying command, run uv tool upgrade, verify server start works with no manual torch step, gate the --index behaviour against the uv 11532 risk flipping docs to the --with fallback if it misresolves, and reproduce the uvx-ephemeral warning and warming status; `docs/verification`.

## Description

Implements the accepted tool-env-gpu-continuity ADR: make the GPU torch contract
survive the uv tool lifecycle and make every failure of it legible. P01 delivers the
env classifier and the exact-command remediation on the CPU-wheel refusal and the
installer warning (ADR A/B/C); P02 the daemon-stamped warming status phase (ADR D);
P03 the jobs json signposting and the canonical install documentation (ADR E plus A
docs); P04 the full-suite run and the mandated on-box manual persona pass, including
the execution-phase gate on uv --index behaviour for tool installs.

## Steps

## Parallelization

P01, P02, and P03 are mutually independent and may run in parallel; within P01,
S01 precedes S02-S04 (they consume the classifier and the command-string helper)
and S05 lands last. S03, S04, and S08 all touch `src/vaultspec_rag/cli/_service_lifecycle.py`,
so parallel phases must serialize edits to that file or run in isolated worktrees.
P04 is strictly last.

## Verification

- Classifier truth-table, refusal-content, and single-source remediation tests pass
  in `src/vaultspec_rag/tests/test_service_env_preflight.py`; status warming fixtures
  pass in `src/vaultspec_rag/tests/test_cli.py`; jobs signpost tests pass in
  `src/vaultspec_rag/tests/test_jobs_unit.py`.
- Full unit and integration suites green locally (machine service stopped, status
  and storage dirs isolated per the singleton-isolation rule); GPU tests run on the
  real box, never skipped.
- On-box persona pass: after installing with the receipt-carrying command, a
  `uv tool upgrade` followed by `server start` succeeds with no manual torch step;
  a uvx-ephemeral run prints the classification warning; `server status` reports
  warming during model warmup with the distinct exit code.
- The uv --index gate is recorded in the P04 step record: either confirmed working
  on Windows `uv tool install` or the documented canonical form flipped to the
  --with wheel fallback before release.
- No json-mode output path emits stray human text (broker envelope contract); the
  jobs envelope shape is unchanged.
- The plan is complete when every Step row is closed.
