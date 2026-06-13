---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S11'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Run the concurrency benchmark against this worktree corpus in local and server modes and record the qdrant-phase delta

## Scope

- `.vault/exec/2026-06-12-qdrant-server-provisioning/`

## Description

- Run the saturation matrix (6 requests, concurrency 3) twice on the same large
  real corpus - the restructure-execution worktree, fully indexed to 24,501 vault
  chunks and 469,317 code chunks - once with the local in-process store and once
  with the supervised Rust server, and record the qdrant-phase delta.
- Migrate the local corpus onto the server by vector copy (point ids, vectors,
  and payloads streamed batch by batch; no GPU re-embedding) so both legs measure
  identical data.

## Outcome

The adversarial A/B is conclusive: the pure-Python local brute-force scan that was
the one hard residual of the concurrency rework collapses to a server HNSW lookup.

Same large corpus (24,501 vault + 469,317 code chunks), concurrency 3, qdrant
search phase mean:

- same-root-code: local 70.887s -> server 0.030s (~2,355x), p50 total 106.7s ->
  2.0s (~54x), throughput 0.028 -> 1.36 rps (~49x).
- same-root-mixed: local 20.688s -> server 0.035s (~583x), p50 total 40.6s ->
  2.7s (~15x).
- same-root-vault: local 3.509s -> server 0.034s (~104x).

A single warm server-mode code search over the 469k-chunk corpus returned in 0.71s
total with an 18 ms qdrant phase, versus the 106s the same query cost in local
mode. The store is no longer the bottleneck on any axis; the residual server-mode
latency (~1-3s) is now the GPU rerank forward pass alone - single-GPU physics, not
software, exactly as the architecture predicted. Result JSONs are persisted at
`tests/benchmarks/baselines/ab_469k_local.json` and `ab_469k_server.json`.

## Notes

- The corpus was migrated by vector copy in ~33 min (I/O-bound, RAM-heavy: the
  local store cold-loads ~34 GB into memory before the copy can scroll it - itself
  an argument for server mode, whose storage is on disk). The watcher concurrently
  re-indexed the same root in server mode during the copy, so the verified counts
  differ by ~0.02% (server 24,512 / 469,225) - effectively complete.
- The earlier deferral (recorded in this step's first draft) cited a contended,
  stale-state service; that state was cleared by a clean restart, the source index
  was completed, and the A/B was then run as described. The win is now measured,
  not merely argued from architecture.
