---
tags:
  - '#audit'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# `service-first-search-fallback` audit: `code review: service-first search routing and bounded local fallback`

## Scope

Adversarial review of the #202 fix: the service-first routing and bounded local
fallback in `src/vaultspec_rag/cli/_search.py` and its regression tests. The
reviewer enumerated port (given/discovered/none) x mandate (true/false) x
service (reachable/dead/live-error) and traced the supporting contracts
(`_try_http_search` returns None only on connection-refused; `_get_search_timeout`;
the canonical `local_only` resolver; the error-envelope shape).

## Findings

- **PASS overall.** No CRITICAL or HIGH. Routing is sound: there is no path
  where local runs without an explicit mandate, and none where a reachable
  service is turned into an error. The deadline covers the whole lock-holding
  window (in-process search plus the lock-releasing `finally`); `os._exit(124)`
  from the daemon timer is the correct tool because OS file-lock release is keyed
  to process death and a normal exception cannot interrupt a wedged native call.
  The #202 symptom cannot recur on any default invocation.

- **MEDIUM (fixed).** `_local_only_configured` originally re-implemented
  `VAULTSPEC_RAG_LOCAL_ONLY` truthiness as a denylist, diverging from the
  canonical config parser's allowlist (`1`/`true`/`yes`) for off-list values
  (e.g. `on`, `enabled`) - the same env var could resolve to server mode in
  config and a local mandate here. Resolved by delegating to
  `get_config().local_only`, the single source of truth; a regression test pins
  the alignment for an off-list value.

- **LOW.** The watchdog timeout envelope is written to stderr with a hand-rolled
  shape rather than through the central JSON emitter. Deliberate and documented:
  the emitter raises `typer.Exit` (unusable off the main thread) and stdout may be
  mid-write; stderr avoids corrupting a partial stdout document.

- **LOW.** Optional extra coverage suggested (an end-to-end local-only-grants-
  mandate routing test); the unit-level mandate path is covered and the
  end-to-end variant would load GPU models, so it is left out of the unit gate.

## Recommendations

- Merge: the blocking MEDIUM is fixed and verified (lint, basedpyright, 12 unit
  tests green). The LOW notes are accepted as-is.
- If the `LOCAL_ONLY` truthiness divergence pattern recurs elsewhere, codify a
  single-parser rule (see candidate below).

## Codification candidates

- **Source:** the ADR's accepted decision and the verified fix.
  **Rule slug:** `search-is-service-first-local-is-explicit`.
  **Rule:** The CLI search router must never execute the in-process local search
  without an explicit operator mandate (`--allow-fallback` or configured
  local-only mode); an unreachable or absent service with no mandate exits with
  the service-down envelope, and any mandated local run is bounded by a
  wall-clock deadline that releases the store lock on expiry. Deferred to a
  follow-up codify pass per the discipline (a rule is promoted after the
  constraint has held across a full execution cycle, not on first landing).
