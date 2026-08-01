---
generated: true
tags:
  - '#index'
  - '#tool-env-gpu-continuity'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:bcc12666e17f4e73d435edcc7af3484a550c9b66f153169ca279d6ac79efbb19'
related:
  - '[[2026-07-14-tool-env-gpu-continuity-P01-S01]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P01-S02]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P01-S03]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P01-S04]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P01-S05]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P02-S06]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P02-S07]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P02-S08]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P02-S09]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P03-S10]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P03-S11]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P03-S12]]'
  - '[[2026-07-14-tool-env-gpu-continuity-P04-S13]]'
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-07-14-tool-env-gpu-continuity-plan]]'
  - '[[2026-07-14-tool-env-gpu-continuity-research]]'
---

# `tool-env-gpu-continuity` feature index

Auto-generated index of all documents tagged with `#tool-env-gpu-continuity`.

## Documents

### adr

- `2026-07-14-tool-env-gpu-continuity-adr` - `tool-env-gpu-continuity` adr: `GPU-torch continuity across uv tool upgrades and env-aware start diagnostics` | (**status:** `accepted`)

### exec

- `2026-07-14-tool-env-gpu-continuity-P01-S01` - Add a pure-path runtime env classifier (installed-tool, uvx-ephemeral, project-venv, other) keyed on sys.prefix vs UV_TOOL_DIR and UV_CACHE_DIR shapes including archive-v0, with \_running_in_uv_tool_env delegating to it, plus a single constant-derived helper producing the escape-hatch command for a given interpreter and the durable receipt-carrying uv tool install command
- `2026-07-14-tool-env-gpu-continuity-P01-S02` - Rewrite the CPU-only messaging in warn_if_active_torch_not_gpu to emit the immediate escape hatch plus the durable receipt fix selected by env classification, sourcing both strings from the new helper
- `2026-07-14-tool-env-gpu-continuity-P01-S03` - Extend the \_preflight_daemon_cuda refusal to print the env classification label beside the Service interpreter path and the exact escape-hatch plus durable-fix commands for the resolved interpreter, dropping the vaultspec-rag install next-action on non-project envs
- `2026-07-14-tool-env-gpu-continuity-P01-S04` - Add a prominent uvx-ephemeral warning to server start, as human text plus a warnings field inside the json success envelope (never stray text), naming the installed-tool path and the stop-the-service-before-forced-reinstall guidance
- `2026-07-14-tool-env-gpu-continuity-P01-S05` - Add classifier truth-table tests (tools dir, archive-v0 cache, project venv, env-var overrides, Windows path shapes), refusal-message content tests, and a single-source test asserting the remediation strings derive from the cu130 constants
- `2026-07-14-tool-env-gpu-continuity-P02-S06` - Add an optional phase field to the service status sidecar schema with writer and reader back-compat treating an absent phase as today's semantics
- `2026-07-14-tool-env-gpu-continuity-P02-S07` - Stamp phase warming into the status sidecar after machine-lock acquisition and before component warmup, and phase running at the lifespan yield, written by the daemon process only
- `2026-07-14-tool-env-gpu-continuity-P02-S08` - Add a warming branch to \_explicit_port_state and the port-only renderer (pid and since rendering, distinct exit code) and make the already-owns-this-machine start message say warming when the sidecar phase says so
- `2026-07-14-tool-env-gpu-continuity-P02-S09` - Add status-state fixtures asserting warming rendering, the distinct exit code, and absent-phase back-compat alongside the existing stopped and unreachable cases
- `2026-07-14-tool-env-gpu-continuity-P03-S10` - Mention --json in the human jobs summary line and command help so scripted consumers are routed to the structured envelope instead of grepping the word active
- `2026-07-14-tool-env-gpu-continuity-P03-S11` - Assert the jobs human summary carries the --json signpost and that the jobs --json envelope shape is unchanged
- `2026-07-14-tool-env-gpu-continuity-P03-S12` - Document the canonical receipt-carrying tool install command with the upgrade contract, the --with wheel-URL fallback, and the ephemeral-env trap including stop-the-service-before-forced-reinstall
- `2026-07-14-tool-env-gpu-continuity-P04-S13` - Run the full unit and integration suites with the machine service stopped and isolated status and storage dirs, fixing any regressions the new surfaces introduce

### plan

- `2026-07-14-tool-env-gpu-continuity-plan` - `tool-env-gpu-continuity` plan

### research

- `2026-07-14-tool-env-gpu-continuity-research` - `tool-env-gpu-continuity` research: `surviving uv tool upgrades on a GPU box`
