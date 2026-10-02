---
tags:
  - '#audit'
  - '#monitor-lifecycle'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:fbf7c2ceb26971e41a14ff0c760913f882e41a4df2a0a73ae262675baa5987a9'
related:
  - "[[2026-10-02-monitor-lifecycle-plan]]"
  - "[[2026-10-02-monitor-lifecycle-adr]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
---

# `monitor-lifecycle` audit: `Focused user documentation review`

## Scope

Review S02's focused README, service guide and generated CLI reference update against base `7ede9843` and the prepared working tree. Governing constraints are accepted monitor-lifecycle, monitor-browser and monitor-tooling. The checkpoint also preserves the initial accepted lifecycle decision and its authorized older-ADR wording; accepting the decision does not establish runtime rollout completion. S01's process implementation and compiled-executable verification remain open.

## Findings

### status-address | low | Status does not display the saved monitor URL

The status summary/detail render the backend address, and the JSON payload does not add a monitor URL: `src/vaultspec_rag/cli/_status_render.py:348`, `src/vaultspec_rag/cli/_status_render.py:919`. The documentation now states this limitation. It directs the operator to the recorded `Monitor:` line from start, including an idempotent already-running response, and names the start envelope's `data.monitor_port` and `data.monitor_url`: `src/vaultspec_rag/cli/_service_start.py:486`, `src/vaultspec_rag/cli/_service_start.py:757`. No status-renderer change was requested or introduced by S02.

## Verification

PASS for S02. The README adds five lines directing users to the local URL, compiled prerequisite, coupled stop and detailed guide. The service guide retains its declared project invocation lane, supplies start/stop and custom-port commands, explains the default 8766-to-8767 candidate and upward fallback, and distinguishes the managed monitor from the source-development server. The generated reference is changed through its canonical notes source, preserving regeneration. The executable prerequisite matches `src/vaultspec_rag/monitor_process.py:37`; port/PID state and coupled cleanup match the prepared runtime paths already reviewed for the initial lifecycle work. These claims describe the authorized implementation contract; delivered-binary behavior remains unverified until S01 receives the artifact.

Working-tree checks: `uv run --no-sync python -m dev.generate_cli_reference --check`, `uv run --no-sync python tools/check_docs_conventions.py`, configured pymarkdown over README/service-mode/CLI, mdformat over authored README/service-mode, ruff lint and scoped format, ty and basedpyright over the generator all passed. Existing CLI start/stop and documentation-convention tests passed: 55 tests. The earlier 244-test service/launcher/configuration check remains applicable to unchanged runtime code. No GPU daemon launch, compiler, release or external publication ran for S02.

## Recommendations

No required documentation corrections remain. Preserve the documented status limitation unless a later request authorizes extending that renderer. Complete S01's real compiled-executable startup, HTTP, allocation, shutdown and mutation proofs before reporting the lifecycle integration complete. Its pending producer artifact does not block this documentation checkpoint.
