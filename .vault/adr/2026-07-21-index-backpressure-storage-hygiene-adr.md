---
tags:
  - '#adr'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:f06a193fff743b4438da937c65bd07fd5e42b4ad581b9f722fe7a11200f5fa0c'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-research]]"
---

# `index-backpressure-storage-hygiene` adr: `fail-loud index write path and ephemeral-namespace hygiene for the shared backend` | (**status:** `accepted`)

## Problem Statement

Issue #242: a 250k-chunk index sat for hours at `completed=0` with the GPU at
100% while Qdrant rejected every write with disk-full errors and crashed
repeatedly. No error reached job progress, `server status`, or `server jobs`.
The disk was full because the shared server backend had degraded unbounded:
117.9 GB across 51 namespaces, 36 rooted in temp dirs minted by harness runs
that never tore down, each empty namespace preallocating ~2.1 GB, temp roots
that still exist classifying `live` and therefore surviving every prune, a
`\\?\` path alias minting a duplicate namespace, and crash-corrupted
config-less collection dirs invisible to survey forever. The failure is
silent, self-inflicted, and recurs by design; this ADR decides the write-path
backpressure model and the storage-hygiene extensions that close all six
handover asks. During recovery the operator recorded a third defect: a
`pytest -m unit` run in a development worktree terminated the shared
machine-global service mid-job (initiator attribution proved it), and the
two killed in-flight jobs vanished from `server jobs` after restart with no
record they ever died. This ADR covers that defect too.

## Considerations

- Research W3: a *raised* upsert already fails the job fast — the machinery
  exists. The wedge (W4) was the encode-side unbounded CUDA-OOM retry loop
  under host-commit exhaustion plus a store client with no explicit timeout
  and no write-side error classification (W5).
- Research W6: job failure reason is free-text; disk-full mapping and the
  300 s stale-progress banner exist only in the CLI renderer, violating the
  spirit of `service-domain-owns-operability`.
- Research S2: `automated-destruction-requires-time-confirmed-danglingness`
  binds any faster temp reclamation — a still-existing temp dir classifies
  `live`, so reclaiming it requires an explicit, persisted, restart-safe
  extension of the danglingness definition, not a shortcut around the rule.
- Research S1: `root_collection_prefix` is the single hashing authority, so
  one normalization fix propagates to registration, teardown, and rekey.
- Research S3 (verified against installed qdrant-client 1.18.0):
  `create_collection` accepts `wal_config`/`optimizers_config`; creation is
  eager in the prepare-collection phase, and the `clean=True` purge relies on
  that eagerness.
- Research S5: survey enumerates only live Qdrant collections; config-less
  dirs need a disk-vs-collections diff to become visible at all.
- The 2026-06-18 storage-lifecycle, 2026-07-14 autoprune-safety, and
  2026-07-14 namespace-hygiene ADRs are composed with, not superseded: HTTP
  stays read-only, destruction stays gated, `storage delete --root` remains
  the sanctioned harness teardown.
- PR 245 (merged to main 2026-07-21, part of defect 2) already landed the
  extended-length alias normalization in `root_collection_prefix`, a
  report-only `temp_rooted` survey flag through the route and CLI emitters,
  and harness-teardown docs. This ADR builds on it rather than redoing it.
  Its investigation disputes the WAL-preallocation premise of ask 5 (the
  ~2.1 GB per leaked namespace was real indexed content), while the
  2026-07-14 autoprune ADR measured ~2.1 GB for zero-point namespaces; the
  claim conflict is resolved empirically before any tuning ships.
- Defect 3's root cause is the same multi-tenancy class as the leak:
  development tooling reaching the machine-global singleton. The
  `managed-singleton-paths-isolate-storage-dir-in-tests` rule already makes
  isolation mandatory, but nothing enforces it structurally, and the
  in-memory jobs registry forgets in-flight jobs on daemon death.

## Considered options

- **Write failure handling: bounded write retry + typed classification
  (chosen)** vs relying on raw propagation (status quo: opaque `str(exc)`
  results, httpx default timeouts, no transient tolerance) vs unbounded
  retry with backoff (recreates the silent wedge). Disk-full classifies
  non-retryable and fails the job immediately.
- **Encode retry: bounded ladder with a floor (chosen)** vs status-quo
  `while True` halving (the proven wedge) vs no retry at all (regresses
  legitimate transient OOM recovery on large batches).
- **Stall surfacing: service-domain stall flag on the job snapshot, rendered
  by every adapter (chosen)** vs CLI-only banner (status quo; invisible to
  brokers) vs a watchdog that kills stalled jobs (risks killing legitimately
  slow work; visibility first).
- **Preflight placement: job-submission boundary in the service domain
  (chosen)** vs CLI-side check (violates `service-domain-owns-operability`)
  vs mid-run enforcement only (burns GPU before refusing).
- **Temp roots: flag at registration + shorter ephemeral idle-TTL reclaim
  tier (chosen)** vs refusing temp roots in server mode (breaks legitimate
  harness runs; a refusal is also trivially bypassed by copying to a
  non-temp path) vs immediate delete on temp classification (violates
  time-confirmed danglingness outright).
- **Empty-namespace cost: tuned collection config at creation (chosen)** vs
  lazy collection creation on first upsert (higher leverage but breaks the
  `clean=True` drop-and-recreate purge contract and widens the blast radius
  across both indexers) vs status quo (~2.1 GB per empty namespace).
- **Test-run protection: suite-level isolation autouse fixture plus a
  lifecycle tripwire (chosen)** vs fixture-only discipline (the incident
  happened despite the rule; discipline demonstrably fails) vs denying the
  lifecycle path to all non-interactive callers (breaks legitimate broker
  automation).
- **Killed-job visibility: persist an active-jobs snapshot and mark prior
  lives' jobs interrupted at startup (chosen)** vs a fully persistent jobs
  registry (heavier redesign; the bounded in-memory ring is a deliberate
  prior decision) vs log-only forensics (status quo; operators do not read
  logs first).
- **Config-less debris: surface in survey + operator-gated reclaim (chosen)**
  vs auto-delete in maintenance (debris has no manifest attribution — the
  `unknown`-never-auto-touched rule forbids it; archive-before-destroy is
  impossible for a collection Qdrant cannot load) vs status quo (invisible
  forever).

## Constraints

- `automated-destruction-requires-time-confirmed-danglingness`: the ephemeral
  tier must run on a persisted clock (manifest `last_indexed` stamp), survive
  restarts, only ever extend protection under races, keep the empty/data
  tier split, and keep archive-before-destroy for data-bearing namespaces.
  `unknown`/`unverifiable` stay untouchable; debris reclaim is manual-only.
- `storage-maintenance-is-lifecycle-inert`: all new hygiene code stays inside
  the regression-tested import graph; no CLI imports.
- `gpu-consumer-single-thread` / `gpu-lock-wraps-forward-passes-only`:
  classification, retries, preflight, and stall detection run outside
  `gpu_lock`; the single-consumer shutdown stays bounded.
- `service-domain-owns-operability`: taxonomy, stall flag, preflight, and
  debris reporting live in `jobs.py`/routes/survey; CLI and MCP adapt.
- `broker-facing-cli-outcomes-are-structured-and-idempotent`: a preflight
  refusal is one structured non-zero envelope with remediation.
- Prefix migration: normalization changes the digest only for `\\?\`-style
  aliases (verified by execution); canonical paths keep their prefixes, so
  no data migration is needed — orphaned alias namespaces age out through
  the existing auto-prune.
- qdrant-client 1.18.0 API is the floor for `WalConfigDiff` /
  `OptimizersConfigDiff`; both verified present in the pinned wheel.

## Implementation

**1. Fail-loud write path.** The store's server-mode client is constructed
with an explicit configurable timeout. Upserts gain a write-side wrapper
(mirroring the search mixin's classification) that maps
`UnexpectedResponse`/`ResponseHandlingException`/transport errors into a
typed `StorageWriteError` carrying an `error_kind` (`disk_full`,
`unavailable`, `timeout`, `rejected`); transient kinds retry a small bounded
number of times with backoff, `disk_full` (Errno 28 / "No space left" /
WAL-capacity messages) is non-retryable and raises immediately. The
embeddings CUDA-OOM recovery becomes a bounded ladder: halve down to batch
size 1, then raise instead of looping forever — persistent allocator failure
aborts the run with the real error. Raised errors flow through the existing
job-failure tail, so the embedder stops and the GPU is released.

**2. Structured job errors + stall surfacing.** The job record gains
`error_kind` (set from `StorageWriteError` or exception mapping in
`record_finish`) and the snapshot gains a computed `stalled` flag (running,
non-waiting, progress age past threshold). Both are served through `/jobs`
JSON and summarized in `server status` and `/health`; the CLI renders from
the shared fields instead of string-matching, and remediation text for
`disk_full` moves to one shared mapping.

**3. Free-disk preflight.** At the job-submission boundary
(`start_reindex_*`, used by the HTTP route, and the in-process CLI path) the
service compares `shutil.disk_usage(qdrant_storage_dir).free` against a
configurable floor plus a coarse estimate derived from the scan's source
byte total. Below the floor the job is refused with a structured
`disk_preflight_failed` outcome naming required vs available bytes and the
reclaim verbs; the CLI exits non-zero with the same envelope in `--json`.

**4. Namespace hygiene.** Alias normalization and the report-only
`temp_rooted` survey flag are already on main (PR 245); this feature adds
the persisted activity clock and the reclaim tier. Manifest registration
refreshes a persisted `last_indexed` timestamp on every index write. The
maintenance cycle gains an ephemeral tier: a temp-rooted namespace (per the
shipped classifier) whose `last_indexed` is older than a configurable idle
TTL (default 72 h) is treated as dangling even though its root exists —
empty ones drop, data-bearing ones archive-then-drop, all through the
unchanged `delete_prefix`/`archive_prefix` gates and per-cycle cap.

**5. Cheap empty namespaces (measurement-gated).** The isolated qdrant
harness first measures a fresh empty namespace's on-disk footprint to
settle the PR-245-vs-autoprune-ADR claim conflict. Only if preallocation is
confirmed as the driver does collection creation gain a small `wal_config`
capacity and reduced `optimizers_config` segment number; otherwise the ask
is closed as answered-by-measurement.

**6. Debris visibility.** Survey diffs the on-disk collections dir against
Qdrant's live collections; unmatched dirs surface as `debris` entries with
footprints, counted in a new total-backend-bytes rollup exposed via survey,
`server status`, and `/metrics`. `server storage prune` gains an explicit
operator-gated flag to remove debris dirs (filesystem removal; the operator
is the confirmation, matching manual-prune semantics).

**7. Shared-service protection from test runs.** The test suite gains an
autouse conftest guard that points `VAULTSPEC_RAG_STATUS_DIR` and
`VAULTSPEC_RAG_QDRANT_STORAGE_DIR` at per-session tmp dirs for every test
and fails fast if either resolves to the machine-global location; the CLI
lifecycle stop/terminate path gains a tripwire that refuses to touch the
machine-global service when running under pytest without explicit
isolation. The jobs registry persists a minimal active-jobs snapshot to the
status dir on transitions; daemon startup reads it and re-registers prior
in-flight jobs with phase `interrupted` (carrying their last progress), so
a killed job remains visible in `server jobs` instead of vanishing. The
observed 10x slowdown under concurrent multi-tenant load is explicitly out
of scope here (performance, not correctness).

**Config knobs** (existing naming conventions): qdrant client timeout,
write retry count, encode-retry floor behavior (fixed, no knob), preflight
enable + floor bytes, ephemeral idle-TTL hours, WAL capacity and segment
number constants.

## Rationale

The incident proved the failure machinery exists but is reachable only via a
clean raise (W3); every fix therefore converges on "convert silent states
into raises or visible flags": bounded encode retries convert the wedge into
a job failure, the client timeout converts a hung server into a raise,
classification converts raw strings into a taxonomy every adapter shares,
and the stall flag covers whatever residual silent state remains.
Refusing work up front (preflight) is the only way to stop burning GPU on
vectors that cannot land, and the submission boundary is the one place all
entry points share (W8). On the hygiene side, flag-plus-TTL is the only
temp-root option that both closes the leak and honors time-confirmed
danglingness: ephemerality is declared at mint time, the idle clock persists
in the manifest exactly like `first_seen_orphaned`, and destruction reuses
the existing gates (S2/S4). Tuned collection config wins over lazy creation
because it delivers most of the disk win with none of the purge-contract
risk (S3). Debris reclaim stays manual because the safety rules make
auto-destruction of unattributable data impossible by design (S5).

## Consequences

- **Gains.** A wedged write path becomes a failed job with an attached,
  classified error within minutes; brokers and operators see stalls and
  disk pressure in every surface; the shared backend stops accumulating
  temp namespaces, alias duplicates, and invisible debris; empty namespaces
  get dramatically cheaper; bulk indexing refuses to start into a full disk.
- **Honest difficulties.** The ephemeral idle-TTL extends the danglingness
  definition — a long-running harness that indexes, idles 3+ days, then
  resumes will find its namespace gone and must reindex (archive covers the
  data-bearing case). The manifest schema grows two fields (absent fields
  behave as non-ephemeral / stamped-on-next-index). Preflight estimates are
  coarse; the floor guards the common case, not exact accounting. Smaller
  WAL capacity trades bulk-ingest throughput headroom for disk (bounded by
  Qdrant's own flushing; acceptable for a single-machine store).
- **Pathways opened.** The `error_kind` taxonomy generalizes to search-side
  errors; total-backend-bytes enables a future size-cap policy; the
  ephemeral flag enables harness-scoped auto-registration affordances the
  dashboard team deferred.
- **Pitfalls to avoid.** Widening `gpu_lock` around retries; a second
  destruction implementation; auto-touching debris; resetting the idle
  clock anywhere but a real index write; letting the CLI keep its own
  error-string matching alive alongside the shared taxonomy.

## Codification candidates

- **Rule slug:** `index-write-failures-fail-the-job-loudly`.
  **Rule:** Every persistent storage-write failure on an index path must
  surface as a failed job with a classified `error_kind` within a bounded
  number of retries; no unbounded retry loop (write- or encode-side) may
  stand between a storage error and job failure.
