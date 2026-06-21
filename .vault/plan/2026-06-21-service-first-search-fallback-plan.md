---
tags:
  - '#plan'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
tier: L1
related:
  - '[[2026-06-21-service-first-search-fallback-adr]]'
  - '[[2026-06-21-service-first-search-fallback-research]]'
---

# `service-first-search-fallback` plan

- [x] `S01` - Add a local-mandate resolver (explicit --allow-fallback or configured local-only mode); `src/vaultspec_rag/cli/_search.py`.
- [x] `S02` - Make routing service-first by dropping the silent auto-fallback and bare-search local path so a search without a mandate exits service-down; `src/vaultspec_rag/cli/_search.py`.
- [x] `S03` - Bound any mandated local run with a wall-clock deadline that releases the store lock and exits non-zero on expiry; `src/vaultspec_rag/cli/_search.py`.
- [x] `S04` - Add regression tests simulating a dead and a wedged service that assert bounded return and a released lock; `src/vaultspec_rag/tests/`.
- [x] `S05` - Run lint, type check, and the search and transport test suite; `pyproject.toml`.
  Make CLI search service-first: never run the heavy local search without an explicit mandate, and bound any mandated local run so it cannot hang holding the store lock (#202).

## Description

Implements the accepted ADR for #202. The CLI search router in `src/vaultspec_rag/cli/_search.py` currently degrades to the unbounded in-process local search in two silent ways - it force-enables the fallback flag whenever it discovers a service port, and it runs local directly when no service is configured - and applies `--timeout` only to the HTTP path, so a mandated local run is deadline-free. This plan removes the silent local-execution paths (service-first; local only on explicit mandate from `--allow-fallback` or configured local-only mode), and wraps any mandated local run in a wall-clock deadline that releases the store lock and exits non-zero on expiry. A regression harness simulates a dead and a wedged service to assert bounded return and no held lock. Grounding: the research and ADR carried in `related:`.

## Steps

## Parallelization

The local-mandate resolver (S01) is the shared dependency for routing (S02) and bounded execution (S03), so it lands first. S02 and S03 touch the same handler and are sequenced. Tests (S04) and the codification follow implementation.

## Verification

- A bare `search` (no `--port`, no mandate) against a down/missing service exits non-zero with the service-down envelope and remediation, and does NOT load models or open the local store.
- `search --port <dead> --allow-fallback --timeout N` returns within a bound near `N` and exits non-zero on deadline, releasing the store lock; a follow-up local search on the same workspace acquires the lock without manual cleanup.
- A mandated local run with no service still works (existing local-only / `--allow-fallback` happy path is preserved).
- New regression tests simulating a dead and a wedged service pass; existing search/transport tests stay green; `ruff` clean; type check clean.
