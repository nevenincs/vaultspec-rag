---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S06'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# convert the qdrant child startup failure into a loud, actionable startup abort that names the install command and the --local-only escape hatch

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Wrapped the `start_supervised_from_config` call in `service_lifespan` in a `try`/`except` that catches any startup failure (binary unresolvable, pre-execution digest mismatch, or readiness timeout) before any GPU memory is committed.
- Emitted a structured `service.lifecycle` / `qdrant_start_failed` error log with `exc_info` so the underlying cause is captured in the service log.
- Re-raised as a `RuntimeError` whose message names the failing default backend, includes the original cause, and gives the two concrete remediations: `vaultspec-rag server qdrant install` to provision the binary, and `vaultspec-rag server start --local-only` to run without the server.

## Outcome

When server mode is the selected backend and the supervised Qdrant child cannot start, the resident service now aborts startup loudly and actionably instead of failing opaquely or silently falling back to the local store, honouring the server-first failure contract in the decision record. The abort fires before model load, so no GPU memory is wasted on a startup that cannot serve. The remediation text points the operator at both the install command and the `--local-only` escape hatch, which is exactly the discoverability the failure contract requires. `ruff check` and `basedpyright` on the changed file are clean.

## Notes

The catch is intentionally broad (`except Exception`) because `start_supervised_from_config` can surface `RuntimeError` (no binary / digest mismatch / not-ready) or `OSError` (spawn failure) and every one of them is a fatal default-path failure that the operator must see remediated; the original exception is chained via `raise ... from exc` and logged with `exc_info`, so nothing is swallowed. The sibling Step S07, which sharpens the message inside `qdrant_runtime/_supervise.py` itself, is outside this executor's exclusive file scope and is left to the owning agent.
