---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
related:
  - '[[2026-06-13-server-first-default-plan]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-06-13-provisioning-setup-adr]]'
  - '[[2026-06-13-server-first-default-audit]]'
---

# `server-first-default` `W04.P10` summary

Execution summary for the server-first reframe (L3 plan, four waves). The feature
flips the RAG backend default to the supervised Qdrant server, unifies external
dependency provisioning behind the `install` front door, and adds a bounded
read-only readiness verb - with local mode preserved as a first-class explicit
opt-out at every layer. 38 of 42 plan Steps are closed here; the four remaining
(`S35`, `S36`, `S37`, `S42`, the human `docs/` reframe) are owned by a separate
documentation worker on the shared branch.

## Modified

- `src/vaultspec_rag/config.py` - `local_only` default + `VAULTSPEC_RAG_LOCAL_ONLY`;
  `effective_server_mode()` (= `qdrant_server and not local_only`); atomic local-only
  marker persistence with precedence env/flag > persisted > default.
- `src/vaultspec_rag/server/_lifespan.py` - startup selects `effective_server_mode()`;
  loud, actionable abort (names the install command and `--local-only`) when the
  supervised child fails.
- `src/vaultspec_rag/qdrant_runtime/_supervise.py` - entry-point failure remediation,
  verify-before-execute intact.
- `src/vaultspec_rag/cli/_service_lifecycle.py`, `cli/_process.py` - `server start
  --local-only` flag, `VAULTSPEC_RAG_LOCAL_ONLY` env translation, default-on
  qdrant-binary guard skipped under local-only, server-first help text.
- `src/vaultspec_rag/commands/_provision.py`, `commands/_install.py`,
  `commands/_models.py`, `cli/_install.py`, `cli/_render.py` - the opt-out
  provisioning front door (sync vocabulary, idempotency, dry-run, two-phase torch
  "configured, sync pending"), wired into `install` with `--local-only`/`--skip-*`/
  `--no-provision` and honest heterogeneous report rendering.
- `src/vaultspec_rag/api.py`, package `__init__.py` - `get_readiness` facade + export.
- `src/vaultspec_rag/cli/__init__.py`, `server/_routes.py` - `server doctor` verb
  registration and the token-gated `GET /readiness` route.
- `.vaultspec/rules/rules/vaultspec-rag.builtin.md` - server-first rule prose;
  `src/vaultspec_rag/tests/test_builtin_rule_directives.py` - guard tokens track the
  reframe.

## Created

- `src/vaultspec_rag/_readiness.py` - service-domain bounded readiness reporter.
- `src/vaultspec_rag/cli/_service_doctor.py` - `server doctor` adapter.
- Tests: `tests/test_config.py` (extended), `test_provision.py`,
  `test_install_provision.py`, `test_readiness.py`, `test_server_doctor.py`,
  `test_cli_server_start.py`, `tests/integration/test_qdrant_server_mode.py`
  (extended), `tests/integration/test_install.py` (extended),
  `tests/integration/test_server_doctor_route.py`.
- `.vault/audit/2026-06-13-server-first-default-audit.md` (persona validation).

## Description

- Verification: 1218 unit tests and 44 feature integration tests pass; ruff, ty, and
  the complexity gate are clean on every changed source file.
- Persona validation (`S40`): PASS. `server doctor` renders the bounded readiness
  snapshot in human and JSON modes (all three dependencies ready on the dev host);
  `install --help`, `server start --help`, and `install --local-only --dry-run`
  surface the server-first defaults and the opt-out flags honestly with the sync
  vocabulary. One LOW observation (CLI-process readiness cannot see daemon-side
  supervised liveness, so `runtime.alive` reads null from a CLI invocation) recorded
  as a doc note, not a defect.
- Code review: PASS - no CRITICAL, HIGH, or MEDIUM findings. The reviewer traced the
  effective-mode precedence, the local-only persistence round-trip and precedence, the
  loud server-start failure contract, and confirmed verify-before-execute (committed
  digest verified before extraction and re-verified before execution, HTTPS
  host-pinned) is not weakened by the front door; readiness is service-domain-owned
  with the CLI verb and route as thin adapters over one snapshot. Two LOW items:
  `SF-01` (a module-level `assert` invariant stripped under `python -O`) was fixed by
  replacing it with an explicit `RuntimeError`; `SF-02` (the doctor verb shipped in a
  new `cli/_service_doctor.py` rather than the plan-named `cli/_service_status.py`) is
  documentation drift already recorded in the `S31` Step Record.
- Codification: none beyond the two ADR-authored candidates
  (`server-mode-is-the-default-backend`, `provisioning-reuses-shared-vocabulary`); the
  validation confirms them rather than surfacing a new cross-session constraint.
