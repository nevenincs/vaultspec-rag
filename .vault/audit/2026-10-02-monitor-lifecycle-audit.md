---
tags:
  - '#audit'
  - '#monitor-lifecycle'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:7e6339fa00d7ba3c4c53197debb9b860b41fd6ca6dbde310badf8cf61c2a384f'
related:
  - "[[2026-10-02-monitor-lifecycle-plan]]"
  - "[[2026-10-02-monitor-lifecycle-adr]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
---

# `monitor-lifecycle` audit: `Focused user documentation review`

## Scope

Review S02's focused README, service guide and generated CLI reference update against base `7ede9843` and the prepared working tree. Governing constraints are accepted monitor-lifecycle, monitor-browser and monitor-tooling. The checkpoint also preserves the initial accepted lifecycle decision and its authorized older-ADR wording; accepting the decision does not establish runtime rollout completion. S01's process implementation and compiled-executable verification remain open.

The integrated S01 review additionally covers the prepared runtime against base `60713f79`, using the finalized Windows executable from delivery producer `957962b342ae1433eee014baa58cff86cb6f942a` and its checksum `64c1aad61d42efd0885932c9707746e9d872f4d0b3b071d88308322ba666898c`. The user has explicitly authorized consolidating delivery into PR #570 and merging all monitor work to main.

## Findings

### status-address | low | Status does not display the saved monitor URL

The status summary/detail render the backend address, and the JSON payload does not add a monitor URL: `src/vaultspec_rag/cli/_status_render.py:348`, `src/vaultspec_rag/cli/_status_render.py:919`. The documentation now states this limitation. It directs the operator to the recorded `Monitor:` line from start, including an idempotent already-running response, and names the start envelope's `data.monitor_port` and `data.monitor_url`: `src/vaultspec_rag/cli/_service_start.py:486`, `src/vaultspec_rag/cli/_service_start.py:757`. No status-renderer change was requested or introduced by S02.

### compiled-lifecycle | low | Runtime and test admission now match the delivered executable

The actual compiled monitor completes upward allocation, shell and bridge HTTP, complete discovery snapshots and heartbeat repair, graceful stop, parent-pipe EOF shutdown and CLI orphan-record cleanup. The test marker now selects the canonical accelerator-free tier. Windows reservations use exclusive wildcard listeners and ports outside the ephemeral range, preserving the exact first-free-port assertion. Removing owned identity deletion and orphan identity deletion independently caused their intended cleanup assertions to fail; exact restoration passed each test. The earlier launcher/incarnation mutation proofs remain applicable.

## Verification

PASS for S02. The README adds five lines directing users to the local URL, compiled prerequisite, coupled stop and detailed guide. The service guide retains its declared project invocation lane, supplies start/stop and custom-port commands, explains the default 8766-to-8767 candidate and upward fallback, and distinguishes the managed monitor from the source-development server. The generated reference is changed through its canonical notes source, preserving regeneration. The executable prerequisite matches `src/vaultspec_rag/monitor_process.py:37`; port/PID state and coupled cleanup match the prepared runtime paths already reviewed for the initial lifecycle work. These claims describe the authorized implementation contract; delivered-binary behavior remains unverified until S01 receives the artifact.

Working-tree checks: `uv run --no-sync python -m dev.generate_cli_reference --check`, `uv run --no-sync python tools/check_docs_conventions.py`, configured pymarkdown over README/service-mode/CLI, mdformat over authored README/service-mode, ruff lint and scoped format, ty and basedpyright over the generator all passed. Existing CLI start/stop and documentation-convention tests passed: 55 tests. The earlier 244-test service/launcher/configuration check remains applicable to unchanged runtime code. No GPU daemon launch, compiler, release or external publication ran for S02.

PASS for S01 in this working tree. The covering compiled process, CLI, discovery, config, lifespan and browser bridge run passed 158 tests. Package ruff, scoped ruff format, ty and basedpyright, production complexity, frontend lint/format/type checks, canonical CLI generation check, documentation conventions and configured authored-document checks passed. Two real compiled cleanup guard mutation sequences recorded exit 1 followed by exit 0 in the tests and the local compiled-lifecycle-guards result. The supervisor source used by the producer interop is unchanged. No inference daemon or production service was started or stopped. Compilation for other native hosts and public acquisition remain delivery-plan evidence obligations; this lifecycle review does not claim those results.

## Recommendations

No required documentation corrections remain. Preserve the documented status limitation unless a later request authorizes extending that renderer. Complete S01's real compiled-executable startup, HTTP, allocation, shutdown and mutation proofs before reporting the lifecycle integration complete. Its pending producer artifact does not block this documentation checkpoint.

The S01 runtime checkpoint resolves the producer prerequisite stated above. Preserve the existing status-output limitation and integrate the completed producer branch through the authorized existing PR.
