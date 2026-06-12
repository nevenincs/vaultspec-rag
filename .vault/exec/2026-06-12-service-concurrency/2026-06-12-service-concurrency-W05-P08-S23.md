---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S23'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Rebuild both corpora under the new schema and run the adversarial saturation matrix against the W01 baseline, recording results

## Scope

- `.vault/exec/2026-06-12-service-concurrency`

## Description

- Restart the shared service onto the reworked code and trigger the one-time
  migrations on both roots: vault point-layout rebuild (one point per chunk) and
  code embed-format rebuild (contextual headers), both via the automatic marker
  detection on an ordinary incremental request.
- Diagnose and fix a migration-scale pathology the rebuild exposed: the local
  Qdrant scroll re-sorts every point id per page, making paged full-collection id
  scans O(N^2) - a 15+ minute GIL-pinned stall on the large corpus that starved
  every other thread. Fixed by skipping the snapshot on clean rebuilds (empty by
  construction) and fetching local-mode id scans as a single page.
- Raise the vault encode sub-batch from 8 to 32 - the old value compensated for
  whole-document inputs of 200-8000 chars; chunked inputs are uniform.
- Run the saturation matrix (8 requests, concurrency 4, 600s timeout) on the
  rebuilt two-root corpus; persist machine-readable results next to the frozen
  pre-rework baseline.

## Outcome

Migration: main rebuilt to 1432 vault chunks; the large corpus rebuilt to 17372
vault chunks plus a full code re-embed - at one point four rebuild jobs ran
concurrently under the index limiter with the GPU measured at 100% utilization
(pre-rework, the same workload idled the GPU behind locks). The limiter telemetry
(borrowed tokens, waiting) was live in the metrics surface throughout.

Post-rework matrix versus the frozen baseline (p50 at concurrency 4):

- same-root-vault: 4.20s to 10.4s. Deliberate quality-for-latency trade: the
  reranker now scores twenty token-bounded full chunks instead of 200-char
  snippets (rerank phase 1.7s to 4.9s, gpu queue wait 2.2s to 5.5s). Latency
  moved from idle lock waits into real GPU relevance work.
- same-root-code: 189s to 250s; qdrant phase mean 149s. The local-mode
  brute-force scan dominates unchanged - it is the named residual.
- same-root-mixed: 95s to 173s; cross-root-mixed: 47s to 59s. Vault searches no
  longer wait on the code collection lock (the split works at the lock level),
  but two effects replaced it: the code searches' content reranks now hold the
  GPU lock for real batches, and the GIL-bound local scans starve co-resident
  Python threads below any lock we control.
- Query-embedding cache proven in production: embedding phase mean 0.0001s in
  the mixed scenarios (repeat queries skip both encoders and the GPU lock).

Attribution is now singular: every slow scenario is bounded by the pure-Python
local store engine (qdrant phase plus its GIL shadow), with reranker batching
second. Both have approved successors (the qdrant server-mode promotion feature;
the reranker evaluation deferral).

## Notes

- The dedicated with-reindex matrix variant was not run separately: the
  multi-hour live rebuild provided richer search-during-index adversarial data
  (a 120s search timeout during the four-job storm, index-slice starvation under
  the pre-rework lock convoy, and the post-fix concurrent-rebuild behavior),
  all recorded here and in the baseline record.
- The shared service was restarted mid-rebuild by the sibling session working
  on this branch (its lifecycle persona tests), killing two rebuild jobs; the
  marker-based rebuild detection recovered cleanly on re-kick - an unplanned
  but successful crash-recovery validation of the migration design.
- An intermediate service generation served a mid-refactor route surface without
  the timing block, costing one discarded matrix run; the final run was taken on
  a service started from committed HEAD state.
