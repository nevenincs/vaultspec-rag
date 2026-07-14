---
tags:
  - '#research'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - '[[2026-06-18-storage-lifecycle-adr]]'
  - '[[2026-07-13-control-plane-affordances-adr]]'
  - '[[2026-07-14-storage-autoprune-safety-adr]]'
---

# `storage-namespace-hygiene` research: `dashboard survey latency and namespace removal asks`

The vaultspec-dashboard team filed a handover (2026-07-14, observed against
released v0.2.28) reporting a machine store polluted with 98 namespaces (~86
test residue), a ~15s `GET /storage/survey` that breaks consumers with sane
read timeouts, and no sanctioned way to remove machine-store namespaces. This
research reconciles their three asks against what main already ships
(unreleased, pending 0.3.0) and isolates the genuine gaps.

## Findings

### F1 - Version skew: every existing remedy is unreleased

PyPI latest is 0.2.28 (2026-07-01). The entire storage-hygiene surface -
`server storage survey|prune|delete|migrate` CLI verbs, the read-only
`/storage/survey` route, and the in-daemon hourly auto-prune - landed on main
after that release and ships only with 0.3.0 (release PR #222, open). The
handover's "check newer versions first" banner therefore resolves to: nothing
installable exists yet; releasing 0.3.0 is a prerequisite for any consumer-side
relief.

### F2 - Ask 1 (removal verb) is substantially answered, but not on HTTP

Main ships two sanctioned removal surfaces:

- `vaultspec-rag server storage prune --yes` removes every `orphaned`
  namespace (`prune_orphaned` in `src/vaultspec_rag/storage_ops.py`); `server storage delete <prefix> --yes` removes one namespace by prefix
  (`delete_prefix`, refusing `unknown` without `--allow-unknown`). Both are
  CLI-direct-to-Qdrant by decision: the storage-lifecycle ADR deliberately
  kept destructive verbs OFF the HTTP control plane so a network caller can
  never destroy data.
- The hourly in-daemon auto-prune (autoprune-safety ADR) removes
  time-confirmed orphans automatically: 24h grace for empty namespaces, 168h
  plus archive-then-drop for point-bearing ones, never touching `unknown` /
  `unverifiable` / `live`. The dashboard's 26 orphans are precisely its diet -
  the store now self-heals without any consumer action.

The residual decision is whether to add a token-gated HTTP mutation
(`POST /storage/prune` or `DELETE /storage/namespace`) as the dashboard's
contract expects, which would partially supersede the storage-lifecycle ADR's
read-only-HTTP boundary. Any such route could reuse `prune_orphaned` /
`delete_prefix` verbatim; the safety question is authorization semantics
(the bearer token currently gates monitoring reads, not destruction).

### F3 - Ask 2 (survey latency) is a genuine, unfixed gap

`gather_survey` (`src/vaultspec_rag/storage_ops.py:165`) is O(namespaces) in
both a sequential `client.count()` loop and a full `os.walk` per collection
directory (`collection_footprints`, line 134). The route
(`storage_survey_route`, `src/vaultspec_rag/server/_routes.py:958`) applies
`?status=`/`?limit=`/`?root=` only AFTER the full gather, so `?limit=` bounds
the response, never the walk - exactly as the dashboard measured (~15-23s at
98 namespaces, scaling with pile size). The footprint walk dominates; counts
against the local Qdrant server are cheap.

Key lever: `run_maintenance_cycle` (`src/vaultspec_rag/storage_ops.py:676`)
already executes the identical `gather_survey` every maintenance interval
(default 60min) inside the daemon. The survey result is computed hourly and
thrown away. Caching the last cycle's classified survey in daemon state and
serving `/storage/survey` from that cache (with a staleness stamp and an
opt-in `?fresh=true` recompute) makes the route O(1) - sub-second at any
namespace count - without a second walk implementation. A cheaper
complementary option is `?fast=true` skipping only footprints (counts +
status live, bytes omitted), useful when the cache is cold (daemon just
started, first tick pending).

### F4 - Ask 3 (test-residue "live" namespaces) is a classification truth, not a bug

The ~60 Temp-root namespaces reported `live` have roots that still exist on
disk - classification is honest (`live` means root path present). No rag-side
heuristic can safely distinguish "dead temp dir" from "valid quiet project";
guessing violates the time-confirmed-danglingness rule. The correct split:

- Consumer side: their harness must delete its temp roots (or register under
  dirs that get cleaned); auto-prune then reaps them after grace.
- Rag side (design question): an ephemeral registration affordance - e.g. a
  manifest `ephemeral` flag set at index/register time - that shortens or
  bypasses the data-tier grace for self-declared throwaway roots. This is a
  manifest-schema and policy extension, small but ADR-worthy since it touches
  the destruction-safety contract.
- Also relevant: `vaultspec-rag clean` only removes the ROOT-LOCAL index
  data; it has never touched machine-store collections. A `clean` that also
  drops the root's machine-store namespace (via the same `delete_prefix`
  path, root resolvable to prefix through the manifest) would give harnesses
  a one-verb teardown. Today the only per-root teardown is `server storage delete <prefix>`, which requires knowing the prefix (obtainable via
  `server storage survey --root <path>` / `?root=`, which main now ships).

### F5 - Our own test suites contribute to the pile

The machine store's residue partly originates from this repo's and core's
harnesses registering real Temp roots against the resident machine service.
Existing mandate (test isolation of `VAULTSPEC_RAG_STATUS_DIR` and
`VAULTSPEC_RAG_QDRANT_STORAGE_DIR`) prevents new residue from THIS repo's
integration tests; the dashboard's vitest live harness intentionally targets
the resident service and needs the F4 affordance or teardown verb.

## Recommendation

Three-part scope, in priority order:

1. **Survey fast path (perf, no new destruction surface):** cache the
   maintenance cycle's survey in daemon state; `/storage/survey` serves the
   cache with `computed_at` staleness metadata, `?fresh=true` forces a
   recompute, and a cold cache falls back to a footprint-free fast gather.
   Closes ask 2 fully and needs no ADR supersession.
1. **Per-root teardown verb:** extend `clean` (or add `server storage release --root`) to drop the root's machine-store namespace through
   `delete_prefix`, giving harnesses sanctioned teardown. Decide HTTP
   exposure explicitly: recommend keeping destruction off HTTP (hold the
   storage-lifecycle line), documenting the CLI verb + auto-prune as the
   sanctioned answer to ask 1, since the auto-prune removes the standing need
   for consumer-driven pruning.
1. **Ephemeral registration (optional, smallest value):** manifest
   `ephemeral` flag shortening grace for self-declared throwaway roots -
   defer unless the dashboard confirms need after 1+2 land.

Plus the operational step outside this feature: ship 0.3.0 so any of this is
installable.

## Sources

- Dashboard handover message (2026-07-14, session transcript).
- `src/vaultspec_rag/storage_ops.py:134` (`collection_footprints` walk),
  `:165` (`gather_survey`), `:676` (`run_maintenance_cycle`).
- `src/vaultspec_rag/server/_routes.py:958` (`storage_survey_route`,
  post-gather filtering).
- `src/vaultspec_rag/cli/_service_storage.py:319` (`storage_delete`), `:383`
  (`storage_prune`).
- PyPI `vaultspec-rag` JSON API (latest 0.2.28); GitHub PR #222 (0.3.0
  release PR, open).
