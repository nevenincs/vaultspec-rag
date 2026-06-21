---
tags:
  - '#exec'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
step_id: 'S04'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# Add regression tests simulating a dead and a wedged service that assert bounded return and a released lock

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add `test_search_service_first.py`: mandate-resolver matrix; deadline fires/cancels/no-op; subprocess proofs that a no-service and a discovered-dead-service search exit non-zero and import no heavy ML library.
- Update the two locked-store CLI tests to pass `--allow-fallback`, since the locked-store message is now reachable only on the mandated local path.

## Outcome

11 new tests pass; the two adapted tests pass; mock-free for new code; status-dir isolated via `VAULTSPEC_RAG_STATUS_DIR`.

## Notes

Dead-service port found via a bind-then-release free-port helper so the connect is refused fast.
