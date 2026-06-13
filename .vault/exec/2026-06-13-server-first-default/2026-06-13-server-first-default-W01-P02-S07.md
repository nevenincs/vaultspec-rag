---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S07'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# surface the loud server-start failure remediation in the start-supervised entry point error message preserving verify-before-execute

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Wrap the `supervisor.start()` call in `start_supervised_from_config` so a spawn or ready-timeout `RuntimeError` is re-raised with the actionable server-first remediation appended: inspect the log, re-run, or fall back to local mode via `vaultspec-rag server start --local-only`.
- Preserve the original failure as the exception cause (`raise ... from exc`) so the underlying reason (port, log path, timeout) is not lost.
- Leave the verify-before-execute contract untouched: the committed-digest re-hash of a provisioned binary still runs before the spawn, so the remediation wrapper never weakens the security boundary.

## Outcome

- A failed server start at the supervised entry point now names the `--local-only` escape hatch alongside the underlying error, matching the loud, actionable failure contract the server-first default depends on. The no-binary and digest-mismatch errors already named their remediations; this closes the remaining ready-timeout/spawn path. `ruff check`/`ruff format`/`ty check` clean.

## Notes

- The lifespan-level abort (W01.P02.S06) and this entry-point wrapper are complementary: the lifespan converts the failure into a service-start abort, while this ensures the entry point's own message carries remediation for any direct caller. The integration coverage for the loud-failure path lives in `test_qdrant_server_mode.py` (W01.P02.S08).
