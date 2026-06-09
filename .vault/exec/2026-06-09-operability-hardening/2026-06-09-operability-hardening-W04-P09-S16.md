---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
step_id: 'W04.P09.S16'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# `operability-hardening` W04.P09.S16 - verification and issue reconciliation

scope: `src/vaultspec_rag/`

## Description

Final verification of the operability-hardening feature: full unit suite, live empirical
service validation of the W01-W03 fixes, formal code review, and issue reconciliation.

## Outcome

- **Unit suite green:** 727 passed, 0 failed (`-m "unit and not subprocess_gpu"`). Two
  regressions surfaced during W03 and were fixed: stale `server service ...` invocations
  in `test_cli.py` (flatten fallout) and a daemon-conflation help string in `_app.py`; plus
  the genuine pre-existing failure (`test_vault_resource_raises_in_http_mode`) was rewritten
  to the post-deconflation REST contract. `ruff` + `ty` clean across the package.
- **Live empirical validation (real GPU/daemon):** daemon started via the flattened
  `vaultspec-rag server start` (PID, 16.6s) under the venv interpreter — no Python-3.14
  protobuf crash (S01). `server status` exit 0; `server logs` now renders real log content
  (S06 `/logs/json` fix); a second `server start` on the busy port returns exit 1 (S05);
  `service.json` carries the `service_token` after start (S10); `server stop` exits 0
  cleanly. The flattened command tree (S12) and the W02 lifecycle fixes are confirmed live.
- **Code review:** conducted by the `vaultspec-code-reviewer` persona on the full feature
  diff.

## Notes

The heavier `subprocess_gpu`/`integration` suites (including the new testimonial tests) are
collected and lint/ty clean; their full live run is the operator validation path. The unit
suite plus the focused live lifecycle check confirm the fixes empirically.
