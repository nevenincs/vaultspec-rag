---
tags:
  - '#research'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:29da2a8798e725a6a0de96227083f5b2217a4a4938fce8527c500bcf482fe913'
related:
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
  - "[[2026-07-14-storage-namespace-hygiene-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
---

# `qdrant-collection-sprawl` research: `why 138 qdrant collections accumulate and never converge`

A workstation audit found the managed qdrant server holding 138 collections across
64 repo hashes, accounting for 27,649 of the machine's 35,872 open `C:` file handles
(77%) and 19.6GB RSS. The question this answers is whether that is a qdrant defect, a
qdrant version problem, or our own. It is ours, and it is not a leak: no handle is
held that qdrant should have released, and the reclamation path works. The store is a
tank filling faster than its drain, and the drain rate was calibrated for a namespace
population that no longer resembles the one being produced.

Five mechanisms were examined. One was already fixed. One is a policy-arithmetic
mismatch. One is an inverted classification that gives a correctly torn-down sandbox
longer retention than a leaked one. Two were found only on a second pass and are
prerequisites rather than consequences: an exception clause that lets a transport
timeout unwind an entire maintenance cycle, and a fixed readiness budget that kills a
healthy but slow qdrant child at this collection count, which stops the reaper from
running at all.

## Findings

### The per-collection cost is qdrant behaving as designed, and no version changes it

We pin `1.19.0` (`src/vaultspec_rag/qdrant_runtime/_constants.py:37`), which is
current. The child is launched with exactly six environment variables and no tuning at
all - host, ports, storage path, snapshots path, telemetry off
(`src/vaultspec_rag/qdrant_runtime/_supervise.py:390`). Every collection therefore
gets default geometry: 2 segments with a full `payload_index` fan-out, at a uniform
150-250 handles.

No upstream defect explains this. Collection-per-tenant is the documented
anti-pattern, not a supported shape: qdrant recommends one collection per embedding
model with payload-based partitioning, and caps Cloud clusters at 1000 collections
precisely because per-collection overhead does not amortise
(https://qdrant.tech/documentation/manage-data/multitenancy/). Our namespacing is
collection-per-repo times three document types, which is that shape exactly.

The 2x handle pairing on mmap-backed files was independently confirmed as expected
behaviour and is not restated here.

### A healthy start costs about two minutes; the observed failure is the daemon not starting at all

Qdrant recovers every collection eagerly and sequentially at boot, with no lazy or
on-demand loading - a long-standing upstream limitation rather than a regression
(qdrant issues 2358, 3935, 7190). The cost is modest: segmenting the rotated logs by
start banner, three separate successful starts each recovered all **139 collections in
1.8 to 2.2 minutes**, roughly 0.9s per collection, before listening.

The damaging behaviour is a different one. `qdrant_ready_timeout_seconds` is a fixed
300s (`src/vaultspec_rag/config/_settings.py:300`, consumed at
`src/vaultspec_rag/qdrant_runtime/_supervise.py:246`). When the page cache is cold,
recovery exceeds that budget, and the supervisor stops a child that is visibly still
progressing and raises. Five such truncated starts are on record, all cut off at
4.8-5.0 minutes: spans of 24, 59, and 90 collections loaded in one log, 58 and 109 in
another. The supervisor's own comment acknowledges the hazard - that quarantining a
still-alive child at the deadline would kill a healthily-loading one - and stops it
regardless.

The sequence is self-resolving but expensive. Each attempt warms more of the page
cache, so successive attempts reach further (24, then 59, then 90) until one completes
and the service comes up; the service was confirmed running afterwards. The cost is
not a permanent deadlock but a burst of consecutive five-minute outages after a cold
start, and the number of attempts required grows with collection count.

This is a prerequisite finding rather than a consequence. `run_maintenance_cycle` has
exactly one caller, `src/vaultspec_rag/server/_lifecycle.py:713`, so the reaper only
runs inside a started daemon. Any retention change is inert for as long as the daemon
is failing to start, which makes the readiness budget a gate on every other fix here.

### The recursive generation suffix is already fixed; the observed names are residue

Doubly- and deeply-suffixed names (`..._g<a>_g<b>_g<c>`, up to ten levels in the
persisted grace ledger) were produced by minting a rebuild generation's name from the
currently *served* collection, which already carried a suffix, so each clean rebuild
widened the next. Commit `e4d1549d` (2026-08-30) changed the mint to derive from the
root's base name; `src/vaultspec_rag/indexer/_generation_lifecycle.py:339` now calls
`generation_code_collection` with `DERIVED_CODE_TABLE_NAME`, and the docstring at
`:317` states the unbounded-growth failure directly.

Two independent facts corroborate that this is closed. Every ledger entry at depth 2
or deeper carries a `2026-08-29` timestamp - the day before the fix. And the current
on-disk census shows 133 collections at suffix depth 0, four at depth 1, one at depth
2, with nothing deeper. Generation nesting is not a live contributor. 13 of the 17
grace-ledger entries name collections that no longer exist, so the residue is ledger
entries more than storage.

### The reaper is not broken - the orphans are almost all still inside their windows

The hourly maintenance tick runs and reports `removed=0 pending_grace=54` on nearly
every cycle, which reads as a stuck grace clock. It is not. Evaluating all 49 orphaned
roots against their own tiered windows, 48 are legitimately pending and exactly one has
just crossed its threshold. The remaining time is not a short tail: the next-shortest
is 10.9 hours and the longest runs to **160 hours**, nearly a full untouched window.
The cycle is declining to act because the policy says not to yet.

The path is demonstrably capable when it does act: the 2026-09-07 23:20 cycle reported
`removed=6 archived=12 swept=2` reclaiming 1.94GB, and an earlier cycle the same day
reached `removed=12 archived=24`. The grace clock is also not resetting spuriously -
`first_seen_orphaned` stamps spread across 2026-09-01 to 2026-09-08 rather than
clustering at the present, which is what a per-cycle reset would produce.

### The driver is an arrival rate comparable to the retention window

46 of 65 manifest roots (70.8%) are throwaway harness sandboxes under the OS temp
directory: 34 under `cadrumo-object-name-*/repository`, 2 post-apply variants, 8 under
`vaultspec-livetest-*`, plus two singletons. The `cadrumo` family averages 83,148
points each - a full repository index. They arrive at 8, 15, 6, 4, and 13 per day over
2026-09-03 to 2026-09-07, a mean of 9.2.

Because each is point-bearing, it is classified data-tier and held for
`grace_hours_data = 168.0` - seven days
(`src/vaultspec_rag/storage_reclamation.py:72`). Steady-state population is arrival
rate times window: 9.2/day times 7 days predicts about 64 namespaces against 46
temp-rooted actually present, agreement to within roughly 40%. The model overshoots
because arrivals are bursty and some sandboxes are reused, but the order of magnitude
is the finding: **no reaping defect is required to explain the sprawl, and fixing one
would not reduce it.**

### Ephemerality is discarded exactly when it becomes certain

There is a 72-hour idle tier for temp-rooted namespaces
(`storage_autoprune_ephemeral_idle_hours`), but its candidate filter admits only
surveys whose status is `live` (`src/vaultspec_rag/storage_reclamation.py:195`). It
was written for the case where a harness temp directory *outlives* its usefulness and
so never classifies orphaned, and its own docstring says so
(`src/vaultspec_rag/storage_survey.py:49`).

The complementary case is the common one. When a sandbox is torn down properly - the
normal, expected outcome - its root vanishes, the namespace classifies `orphaned`, and
it routes to `_decide_orphan`, whose tier and window selection reads only
`survey.points` and never consults `is_temp_rooted`
(`src/vaultspec_rag/storage_reclamation.py:317`). It therefore draws the full
168-hour data window. A sandbox that cleans up after itself earns **2.33x** the
retention of one that leaks its directory, and the strongest available evidence of
ephemerality - the root is provably gone *and* it was always temporary - is the
evidence the policy ignores. This is the one clear defect in the reclamation policy.

### A transport timeout unwinds the whole maintenance cycle

The 2026-09-07 15:57 tick died with `error_kind=timeout` and reclaimed nothing. The
cause is an exception clause, not a budget. `archive_prefix` snapshots each collection
via `client.create_snapshot(..., wait=True)`
(`src/vaultspec_rag/storage_reclamation.py:425`), and the qdrant client raises
`httpx.ReadTimeout` on a slow snapshot. The guard wrapping the archive call catches
only `(OSError, RuntimeError)` (`src/vaultspec_rag/storage_reclamation.py:696`).
`httpx.ReadTimeout` inherits `TimeoutException` to `TransportError` to `RequestError`
to `HTTPError` to `Exception` and is a subclass of neither, verified directly against
the installed client, so it walks past the handler and unwinds the entire cycle rather
than marking one namespace failed.

The same hole exists on two safety-relevant paths: `_prefix_points`
(`src/vaultspec_rag/storage_reclamation.py:120`) and `_active_index_prefixes`
(`:149`). A read timeout on the pre-drop re-count aborts the cycle instead of
deferring that namespace. The accepted parent contract already requires that any gate
failing skips the prefix and reports why, so this is an unimplemented clause of a
shipped decision rather than a new capability.

### The archive cap bounds retention, not drain rate - and it is about to turn over

The archive holds 44 entries totalling 21,122,717,394 bytes, **98.36%** of its
`storage_autoprune_archive_max_gb = 20.0` cap (`src/vaultspec_rag/config/_settings.py:97`).
It is tempting to read this as a brake on reclamation; it is not. `archive_prefix`
performs no cap check, and `sweep_archive`
(`src/vaultspec_rag/storage_reclamation.py:535`) runs at the *end* of a cycle,
evicting oldest-first to make room. Nothing refuses a reclaim because the archive is
full. Drain rate is bounded by `max_per_cycle = 16` and snapshot write throughput; the
cap governs how long evidence survives.

That distinction matters because of what a retention fix triggers. Every temp-rooted
orphan stamp is already 8 to 160 hours old, so shortening their window makes all 40
eligible on the first cycle. Their footprint is 49,701,190,154 bytes (46.3 GiB) across
40 namespaces, about 1.16 GiB each; 16 per cycle is roughly 18.5 GiB against a 21.47 GB
cap that is already 98% full. **One or two cycles turn the entire archive over**, so
the nominal 30-day retention collapses to roughly one cycle for the duration of the
drain.

### The archive is not restorable on the affected platform

Archive-before-destroy is the safety property that makes a data-tier drop acceptable,
and the parent contract's wording requires a *recoverable* archive. On Windows that
word is currently unsatisfied: `src/vaultspec_rag/qdrant_runtime/_constants.py:42`
defines `WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON`, and the operator-facing
path (`src/vaultspec_rag/cli/_service_storage.py:1028`) tells the operator to restore
on a non-Windows server. The archives remain portable, so recovery is possible but not
in place. The host in this audit is Windows 11, so any "the worst case is a
recoverable archive" reasoning must be qualified on this platform.

### Nothing bounds the collection count, and the reachable effect size is partial

All safety in this path is time-based and per-namespace. There is no cap on total
collections, no cap per repo, and no back-pressure when the count rises, so any future
harness that outruns the window reproduces this exactly.

The reachable win should not be overstated. Classifying all 138 on-disk collections
against the manifest gives 77 orphaned and temp-rooted, 27 orphaned and non-temp, 29
live and non-temp, 5 live and temp-rooted. A retention change for the ephemeral class
touches only the first bucket; the 27 non-temp orphan collections belong to deleted
git worktrees and keep the 168-hour window. At 9.2 temp namespaces/day and about 1.93
collections each, a 24-hour ephemeral window leaves roughly 18 in flight, for a steady
state near **79 collections** rather than the 34 live ones - a 43% reduction, not the
75% a naive reading suggests.

### The confirming signal for a deferred affordance has arrived

The prior namespace-hygiene decision deliberately deferred an ephemeral-registration
affordance - letting a harness declare a namespace throwaway at creation - until need
was confirmed. 46 of 65 roots being harness sandboxes is that confirmation. Whether
to revive registration, infer ephemerality from the root path as the reclaim path
already does, or have harnesses tear their namespaces down at exit, is left to the
ADR.

### Option space, and what was not investigated

Two findings are prerequisites and should be sequenced first: a readiness budget that
tolerates a live, progressing child, and the exception clause that lets one slow
snapshot abort a cycle. Neither is a retention question, and retention changes are
inert until both hold.

On retention itself, the evidence favours discriminating by namespace class over
building new reaping machinery, since the reaper works and the windows are the
mismatch. The open axes are: carrying `is_temp_rooted` into the orphan decision so
ephemerality survives teardown, and at what window; a count-based backstop, and
whether it may modulate throughput without becoming an authorisation; whether the
archive cap should be raised to cover the drain, given that it will otherwise turn over
wholesale; and stopping production at the source, which is only partly available since
the dominant producer is a foreign harness. Our own `vaultspec-livetest-*` residue is
in scope and indicates tests reaching the operator's real backend.

The qdrant-side shape change - payload partitioning instead of collection-per-repo -
is the upstream-recommended fix and would remove the class outright, but it is a
storage-schema migration far larger than this defect and is named here only so the ADR
can size it against the alternatives.

Not investigated: whether qdrant's per-structure memory tiers would materially reduce
RSS at this collection count; whether reducing `default_segment_number` below 2 is safe
for our query shapes; the RSS attribution across collections, taken from the audit
rather than re-measured; and why the `cadrumo` harness indexes a fresh full repository
roughly nine times a day.

## Sources

- `src/vaultspec_rag/qdrant_runtime/_constants.py:37`
- `src/vaultspec_rag/qdrant_runtime/_constants.py:42`
- `src/vaultspec_rag/qdrant_runtime/_supervise.py:246`
- `src/vaultspec_rag/qdrant_runtime/_supervise.py:390`
- `src/vaultspec_rag/storage_reclamation.py:72`
- `src/vaultspec_rag/storage_reclamation.py:120`
- `src/vaultspec_rag/storage_reclamation.py:149`
- `src/vaultspec_rag/storage_reclamation.py:195`
- `src/vaultspec_rag/storage_reclamation.py:317`
- `src/vaultspec_rag/storage_reclamation.py:425`
- `src/vaultspec_rag/storage_reclamation.py:535`
- `src/vaultspec_rag/storage_reclamation.py:696`
- `src/vaultspec_rag/storage_survey.py:46`
- `src/vaultspec_rag/storage_survey.py:49`
- `src/vaultspec_rag/indexer/_generation_lifecycle.py:317`
- `src/vaultspec_rag/indexer/_generation_lifecycle.py:339`
- `src/vaultspec_rag/server/_lifecycle.py:713`
- `src/vaultspec_rag/cli/_service_storage.py:1028`
- `src/vaultspec_rag/config/_settings.py:97`
- `src/vaultspec_rag/config/_settings.py:300`
- commit `e4d1549d`
- `qdrant@1.19.0`
- https://qdrant.tech/documentation/manage-data/multitenancy/
- https://github.com/qdrant/qdrant/issues/2358
- https://github.com/qdrant/qdrant/issues/3935
- https://github.com/qdrant/qdrant/issues/7190
- Live measurements 2026-09-08 from `~/.vaultspec-rag/storage-manifest.json`,
  `~/.vaultspec-rag/generation-grace.json`, `~/.vaultspec-rag/service.log`,
  `~/.vaultspec-rag/qdrant.log` and its rotations, and the collections and archive
  directories under `~/.vaultspec-rag/qdrant-server/`.
