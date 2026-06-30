---
tags:
  - '#audit'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-30'
related:
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-12-service-concurrency-plan]]"
---

# `service-concurrency` Code Review

Two parallel reviewer passes (concurrency core; search quality + transport) against
the feature ADR. Verdict: PASS - no CRITICAL or HIGH findings. Four MEDIUM findings
were fixed in-branch immediately after this review; the remainder are LOW
observations kept for the record.

## META-01 | MEDIUM | Reserved schema marker leaks into file-id set arithmetic

`_load_meta` returned the raw sidecar including the reserved layout/embed marker
keys, so the codebase incremental path counted the marker as a deleted file every
run (over-reporting `removed` by one) and fed a phantom path into the
delete-filter. FIXED: both indexers now strip reserved dunder keys in `_load_meta`
and the rebuild detectors read the raw sidecar directly.

## WATCH-01 | MEDIUM | Double record_finish on watcher cancellation

The watcher's cancellation branch finished the job record, then the outer cleanup
finished the same record again (the caller's assignment never ran after the raise),
garbling terminal job telemetry. FIXED: `record_finish` is now idempotent - a
record that already carries `finished_at` is left untouched and the duplicate is
logged at debug.

## SEARCH-01 | MEDIUM | Vault grouping could under-fill top_k

Reranking truncated to twice top_k before chunk-to-document grouping, so a heavily
chunked document dominating the rerank window could collapse the final page below
top_k documents. FIXED: the vault path now reranks the full fetched candidate set
and truncates only after grouping.

## EMBED-03 | MEDIUM | Query cache returned aliased sparse objects

Cache hits handed every caller the same SparseResult instance; safety relied
incidentally on one downstream list() copy. FIXED: the cache returns a defensive
copy of the sparse component on get.

## EMBED-01 | MEDIUM->verified | Qwen3 instruction template byte parity

The per-surface instruction prompts hard-code the Qwen3 instruction format outside
the model's prompt registry. Verified against the model's shipped query prompt that
the instruction-then-query prompt shape including its trailing space matches; noted
as a coupling to re-verify on any embedding-model swap.

## LOCK-01 | LOW | Closed-store point op raises rather than degrades

A point operation racing `close()` between its ensure and its point-lock
acquisition raises the closed-store RuntimeError. Narrow window, eviction only
closes refcount-zero slots; acceptable, recorded.

## LOCK-02 | LOW | Lock ordering verified safe

Lifecycle lock strictly precedes collection locks at every multi-lock site; point
operations never nest collection-to-lifecycle. No inversion across lifecycle,
collection, writer, and GPU locks.

## RLOCK-01 | LOW | Intentional reentrancy in id-scan sizing

`_id_scan_page_limit` re-acquires the collection lock under callers that already
hold it; safe because collection locks are reentrant. A clarifying comment was
added so a future switch to plain locks cannot silently deadlock.

## SCAN-01 | LOW | Single-page scans are payload-light

All single-page local scans project only id fields with vectors off; the only
full-payload listing keeps bounded paging. No memory blowup.

## WATCH-02 | LOW | Benign double-warm race in deferred watcher start

Two concurrent cold-root requests can both schedule the slot warm-up; the terminal
double-check still guarantees a single watcher. Wasted duplicate cold open only.

## LIMITER-01 | LOW | Limiters are loop-bound singletons

Safe under the daemon's single event loop; the latent multi-loop hazard is
mitigated by the tests-only reset helper. Recorded for test authors.

## CHUNK-01 | LOW | Chunk budget not strictly enforced on pathological input

A separator-free over-budget line can yield one oversized chunk; downstream embed
truncation and the reranker char cap absorb it. Recorded; strict enforcement left
to the splitter if it ever matters.

## SEARCH-02 | LOW | Group tie-break is insertion-order dependent

Equal-scored chunks keep the first-seen snippet; deterministic within a run.
Cosmetic.

## SEARCH-04 | LOW | Cache hits zero the embedding phase

On a query-cache hit the embedding phase reads ~0 and no GPU wait is recorded;
operators cannot distinguish a hit from an instrumentation gap. Candidate for a
cache-hit flag in a future timing slice.

## STREAM-01 | LOW | Length-sort keys under-count header overhead

Sort keys omit the small title/header additions to embed text; padding-uniformity
intent survives. Performance-only.

## MCP-01 | LOW | Transport rewrite complete

All MCP tools, admin tools, and resources dispatch through the thread-backed async
wrapper; no missed synchronous call sites; the timeout env var now governs all
daemon round trips (broader than its name implies - documentation candidate).

## MCP-02 | LOW | MCP client side uses the default thread pool

The stdio client's loopback calls draw from the default pool rather than a
dedicated limiter; fine at stdio concurrency. Recorded.

## TEST-01 | LOW | Test compliance verified

New tests are real-GPU/real-Qdrant, non-tautological; one sparse-parity test
couples to ascending intra-row order that coalesce happens to produce. Recorded.

## Verdict

PASS. The lock split has a consistent global acquisition order; the migration
markers, shrunk-tail purge, and clean rebuilds all run under the writer lock; the
cache, nudges, and transport changes are safe. The four MEDIUM items above were
fixed and re-tested in-branch the same day.
