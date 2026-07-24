---
tags:
  - '#adr'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-worktree-index-reuse-research]]"
---

# `worktree-index-reuse` adr: `encode-seam read-through vector reuse by point id` | (**status:** `accepted`)

## Problem Statement

Indexing a new git worktree forked from an already-indexed branch recomputes every embedding on the GPU although the vectors already exist byte-for-byte in a sibling namespace: the namespace is keyed on the root path while point identity is exact-content-addressed (grounded in `2026-07-24-worktree-index-reuse-research`). Rebuild-class jobs cost 2,935-4,495 s on this box with encode dominating roughly 100x over chunking; forks are frequent in this project's worktree-based workflow. A decision is needed on the reuse mechanism before any implementation, because the wrong mechanism either introduces a silent-stale-vector class or a new storage lifecycle surface.

## Considerations

- Encode dominates the rebuild roughly 100x; donor lookup throughput is measured at about 2,345 pts/s - reuse is bounded by correctness design, not IO (research spikes 2-3).
- Git identity is provably not byte identity on this box (96/2,396 tracked files CRLF-divergent under clean status); the digest layer subsumes git detection (research spike 1).
- A stale well-formed vector is silent ranking degradation with no cheap oracle - the reuse key must be complete and the reuse guard tests must prove they can fail.
- Automated-destruction safety, storage-maintenance inertness, and the 1:1 prefix-to-root invariant must remain untouched; any new on-disk state would demand its own danglingness design.
- GPU discipline is fixed: single consumer thread, `gpu_lock` wraps forward passes only, workers CPU-only, torch through the centralized gate.
- Both backends matter: server mode (default) has cross-namespace donors in one Qdrant server; local mode donors require same-process store handles.

## Considered options

- A - namespace clone (donor-match then scroll-and-upsert wholesale): fast exact copy, but the clone decision is a corpus-level similarity judgment and donor-only stale points linger. Rejected: correctness rests on a heuristic.
- B - durable machine-global KV hash-to-vector cache: exact keying, but a third copy of every vector, a new machine-global lifecycle surface with no root attribution (the `unknown` class auto-destruction must never touch), and the full key-completeness hazard. DEFERRED, not rejected: stage-2 candidate, reconsidered only if stage-1 telemetry shows sibling namespaces frequently absent when needed.
- C-prime - payload-partitioned shared collections (root-as-tenant): true storage dedup, but falsifies the 1:1 prefix-to-root invariant the delete/autoprune safety surface is built on, inverts grace semantics to membership refcounts, degrades local mode, and re-concentrates writes against the lock-split lesson. DECOUPLED: a separate future ADR about storage dedup; explicitly not bundled behind the GPU fix.
- Git-based divergence detection (as a correctness or gating layer): REJECTED outright - git identity is not byte identity (measured), it misses preprocess outputs, dirty state, submodules, LFS, and non-git roots, and the stage it would accelerate costs about 1 s. The digest layer subsumes it.
- CHOSEN - encode-seam read-through reuse by point id: retrieve-by-id from sibling donor namespaces before encoding, verify content, adopt vectors on hits, encode misses.

## Constraints

- Donor lookups must run OUTSIDE `gpu_lock` and on the existing single consumer thread; no new threads, no CUDA streams, chunk workers untouched.
- Zero new on-disk state: no cache files, no manifest schema change, no lifecycle/autoprune/survey surface change. The storage manifest is consulted read-only for donor candidates.
- The service call paths stay torch-free; nothing in the reuse path imports torch.
- Local mode: donors are limited to store handles the same process already holds (the embedded backend is single-process); server mode is the primary target and ships first.
- Depends only on stable in-repo machinery: deterministic point ids, payload content fields, config-epoch sidecars, the storage manifest. No new libraries, no frontier features.

## Implementation

At the single encode seam, before a batch is encoded: compute the batch's deterministic point ids (already deterministic today); retrieve those ids with vectors from up to N candidate donor collections; verify each fetched point's payload content equals the expected chunk content byte-for-byte; on a verified hit adopt the donor's dense and sparse vectors onto the chunk; GPU-encode only the misses; upsert everything into the root's own namespace exactly as today. Payloads are always rebuilt locally - vectors are the only thing reused.

Reuse-key / eligibility contract (all gates must pass before a donor namespace is consulted):

- same collection kind (vault/codebase/document suffix),
- identical dense vector dimensionality and named-vector layout,
- identical embedding model identity, including model revision,
- identical content-epoch sentinel for the collection kind (the sidecar-stamped content epoch of the donor root matches the indexing root's effective epoch),
- per-point: fetched payload content field equals the expected chunk content (closes 63-bit point-id collisions and any residual key incompleteness).

Donor-candidate selection reads the storage manifest (prefix, root, backend, last-indexed), filters by the gates above, ranks siblings of the same repository family first, and caps candidates at N. Donor selection affects only hit rate, never correctness.

Operability: an off-switch flag (config + CLI surface consistent with existing knobs) defaults ON and disables all donor lookups when off, restoring today's behavior exactly - the A/B lever and the paranoia escape hatch. Telemetry counters recorded per index job: reuse hit count and rate, GPU-seconds saved (estimated from measured encode throughput), donor-absent rate, fork wall-clock. These are also the stage-2 decision inputs.

Guard tests must prove they can fail: for each eligibility gate (content verify, dims, model identity, content epoch) mutate the gate so forbidden reuse is permitted, observe the specific assertion go red, restore, observe green, and record both directions where the test's reader will find them.

## Rationale

Reuse-by-point-id is the only option that is exact AND verified with zero new state: a hit is byte-identical content confirmed against the donor's own payload, so no corpus-similarity judgment exists anywhere in the design - divergent content cannot be reused because it misses, and a miss simply pays today's cost. It captures B's entire GPU win (encode dominates roughly 100x; lookup throughput is 3 orders of magnitude above need) while deleting B's costs: no third vector copy, no GC, no autoprune extension, no unattributable machine-global state. It leaves every safety invariant untouched - per-root namespaces, the prefix-to-root manifest, delete guards, grace clocks - which C-prime cannot claim. Two independent analyses (the spike-driven derivation and an adversarial review argued from the project safety rules) converged on it (`2026-07-24-worktree-index-reuse-research`).

## Consequences

- Measured validation (fork of this repository, live service, code domain, single shared 16 GB GPU, embedded-local support profile): the flag-OFF from-scratch rebuild baseline is 311 s (~1,988 code chunks, ~4.6-5.0 GB peak CUDA, constrained support profile and encode batch to fit the shared GPU). The first measurement attempt showed an effective 0% hit rate with no reuse telemetry; this was root-caused to a served-record plumbing defect, not a resolver miss - the reuse block rode only the legacy activity record while the canonical `JobManager` snapshot the service serves carried no reuse field, so every daemon-dispatched job served `reuse: null` regardless of what the run adopted, and the measurement-time daemon process predated the seam code. The defect was fixed (the reuse block now travels on the canonical `JobSnapshot`), a guard integration test at the job-record layer proves it red-then-green, and the daemon was redeployed on the current tree and re-measured. On the re-run the reuse block is present and populated and the feature engages end-to-end. Against a byte-identical fork (a byte-for-byte copy whose stored bytes match the donor exactly) the flag-ON code rebuild adopts every vector: 100.0% hit rate (6,424 hits / 0 misses), 28.7 s wall-clock, ~128 estimated GPU-seconds saved - HEADLINE 311 s -> 28.7 s, a 10.8x wall-clock reduction with zero forward passes for the corpus. Against a `git worktree` checkout of HEAD (donor = the live sibling namespace) the rebuild reused 69.2% (4,448 hits / 1,976 misses), 45.8 s wall-clock (6.8x under baseline) - and the miss share was subsequently root-caused as a MEASUREMENT ARTIFACT, not a feature limitation and not line endings: the donor namespace indexed the sibling's dirty working tree, which carried this feature's own then-uncommitted source files, while the fork checked out clean HEAD without them, so the largest files in the repository genuinely differed and were correctly refused. Line-ending divergence cannot cause verify misses at all: the chunker normalises newlines at decode time, so donor-stored content and expected content are both normalised - verified by a direct probe (CRLF file vs LF twin through the real chunker produce byte-identical chunk ids and contents). A real same-commit worktree fork therefore approaches the ~100% of the byte-identical leg. Both acceptance signals hold on the clean leg: ~100% hit rate on the served record AND a large real wall-clock drop versus the 311 s baseline.
- Every pair of roots with overlapping content benefits, not only worktrees; dead-worktree namespaces keep serving as donors through the autoprune grace window.
- The per-root storage duplication remains (mitigated separately by segment-geometry bounding); storage dedup stays a separate future decision (C-prime), and the durable KV cache (B) stays a telemetry-gated stage 2.
- New failure surface is confined to the eligibility gates; the content verify bounds the blast radius of any future key drift to a per-point compare, and the off-switch restores baseline behavior in one flip.
- Donor lookups add bounded read traffic to the shared Qdrant server during indexing; measured throughput makes this negligible against encode time, but the prototype confirms it end-to-end.
