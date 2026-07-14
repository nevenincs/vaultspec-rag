---
tags:
  - '#adr'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-storage-namespace-hygiene-research]]"
  - "[[2026-06-18-storage-lifecycle-adr]]"
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
---

# `storage-namespace-hygiene` adr: `survey snapshot cache and per-root teardown` | (**status:** `accepted`)

## Problem Statement

The vaultspec-dashboard team (consuming the codified HTTP control plane)
reported two operability failures at 98 stored namespaces: `GET /storage/survey` takes ~15-23s because it walks every collection's on-disk
footprint per call (any consumer with a sane read timeout fails closed), and
there is no sanctioned one-verb way for a consumer or test harness to remove
the machine-store namespace of a root it owns. The research reconciled their
asks against main: automated orphan removal already exists (auto-prune), but
survey latency is a real gap and per-root teardown requires knowing the
internal `r{hash}_` prefix.

## Considerations

- The daemon's hourly maintenance cycle already computes the identical full
  survey (`gather_survey` inside `run_maintenance_cycle`) and discards it.
- The footprint `os.walk` dominates survey cost; Qdrant point counts against
  the local server are cheap.
- The storage-lifecycle decision keeps destructive verbs OFF the HTTP plane;
  the autoprune-safety decision permits automated destruction only under
  time-confirmed danglingness. Both are reaffirmed, not superseded.
- `root_collection_prefix(root)` derives a root's namespace prefix
  deterministically, so a root-addressed delete needs no new resolution
  machinery, and the existing `delete_prefix` safety gates (canonical-prefix
  regex, unknown-namespace refusal) apply unchanged.
- Broker-facing CLI outcomes must be structured and idempotent: a teardown of
  a namespace that does not exist is a success, not a fault.

## Considered options

- **Serve survey from a daemon-held snapshot cache (chosen for latency):**
  reuse the maintenance cycle's survey; O(1) route at any namespace count.
  Con: bounded staleness between ticks - mitigated by `?fresh=true` and
  mutation-free honesty metadata (`computed_at`, `source`).
- **Bound the walk by `?limit=` / parallelize the walk:** still O(pile) on
  every call, complexity grows with no ceiling; rejected.
- **`?fast=true` footprint-free variant only:** closes the timeout but loses
  byte data the dashboard renders; kept only as the cold-cache fallback
  behavior, not the primary fix.
- **Root-addressed delete on the existing CLI verb (chosen for teardown):**
  `server storage delete --root <path>` alongside the prefix argument; reuses
  envelope, gates, and docs. Con: none material.
- **Extend `clean` to drop machine-store namespaces:** changes the blast
  radius of a local-only verb that must work without a server; rejected.
- **Token-gated HTTP prune/delete route:** collides with the read-only HTTP
  boundary; the monitoring bearer token was never scoped as a destruction
  credential, and auto-prune removes the standing need; rejected.

## Constraints

- The snapshot cache must not create a second survey implementation: one
  `gather_survey`, multiple consumers.
- Cache readers and the maintenance-thread writer share daemon state; the
  handoff must be a single atomic reference swap (no partially built
  snapshot ever visible).
- The startup warmer is survey-only (read-only). Maintenance modules must
  remain lifecycle-inert and must still never import `vaultspec_rag.cli`.
- CLI-direct mutations (operator prune/delete) bypass the daemon, so the
  cache can be stale for up to one interval after them; the envelope must
  carry `computed_at` so consumers can see this, and `?fresh=true` must
  recompute and repopulate.
- Root-addressed delete must resolve the root exactly like registration does
  (same normalization feeding `root_collection_prefix`) or teardown will
  silently miss.

## Implementation

**Survey snapshot cache.** Daemon state gains a survey snapshot slot: the
classified survey list plus `computed_at`. Writers: a startup warmer task
(runs once, shortly after lifespan start, survey-only) and every maintenance
cycle (which already computes the survey; it publishes instead of
discarding). `/storage/survey` serves the snapshot when present, applying
the existing `status`/`limit`/`root` filters to the cached list, and reports
`computed_at` and `source: "cache"`. `?fresh=true` (and a cache miss) runs
the live gather in the route's worker thread, publishes the result, and
reports `source: "fresh"`. The envelope stays backward-compatible -
new fields only. CLI-direct survey (`server storage survey` against a
stopped daemon) is unchanged.

**Per-root teardown.** `server storage delete` accepts `--root <path>` as an
alternative to the positional prefix: the root is normalized exactly as
registration normalizes it, converted via `root_collection_prefix`, and
dispatched through the unchanged `delete_prefix`. A vanished namespace
(`no_such_namespace`) exits 0 in both human and `--json` modes with an
`already_absent`-style status, making harness teardown idempotent. The
`--json` envelope carries the resolved prefix and the queried root.

**Docs and reply.** `docs/cli.md` and `docs/storage-maintenance.md` document
the teardown recipe for test harnesses (delete-by-root on teardown; or rely
on auto-prune after removing the temp root) and the survey freshness
semantics. The dashboard reply states the HTTP plane stays read-only and
names `server storage delete --root ... --json` as the sanctioned teardown
verb.

## Rationale

Research F3 identified that the hourly maintenance tick already pays the full
survey cost and throws the result away - caching it is the only option that
makes the route O(1) without a second implementation, and it composes with
the tick cadence consumers already accept for reclaim behavior. Research F2/F4
showed removal is already solved for orphans (auto-prune, CLI prune) and that
the only genuine teardown gap is prefix addressing; `--root` on the existing
delete verb closes it with near-zero new surface. Keeping HTTP read-only
reaffirms the storage-lifecycle boundary: the monitoring token must not
become a destruction credential, and with auto-prune shipped the consumer no
longer needs to mutate at all.

## Consequences

- `/storage/survey` becomes sub-second at any namespace count; the dashboard
  reverts its widened 45s budget after 0.3.x lands.
- Survey data is eventually-consistent (≤ one maintenance interval, or
  explicit `?fresh=true`); consumers get honest `computed_at` metadata.
- Test harnesses (dashboard vitest, core fixtures) get one idempotent
  teardown verb; the residue pile stops growing at its source.
- The ephemeral-registration affordance (research part 3) is deliberately
  deferred until the dashboard confirms need after these land.
- Everything here ships no earlier than the next release; the dashboard's
  version banner is answered by shipping 0.3.0.
