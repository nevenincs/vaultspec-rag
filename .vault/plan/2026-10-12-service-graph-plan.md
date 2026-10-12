---
tags:
  - '#plan'
  - '#service-graph'
date: '2026-10-12'
tier: L1
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-03-07-vaultgraph-cache-adr]]'
modified: '2026-10-12'
body_schema: body-v2
body_hash: 'sha256:907f8e26cfdf88bc76cac45eba772a8aedff083ca1f84b244db281795c653d66'
---

# `service-graph` plan

## Description

Approved 2026-10-12

The user authorized fixing the measured vault search stall, then explicitly requested
separate optimization of graph calculation after the blocking fix is verified.
The amended graph-cache and service-graph decisions govern S01. S02 profiles and
optimizes the canonical graph implementation without introducing a duplicate parser,
changing persisted graph semantics, or weakening filesystem containment checks.
The existing feature branch and existing directories are used. No index rebuild or
storage deletion is required for this work.

## Steps

- [x] `S01` - Remove synchronous graph construction from search and verify lifecycle races and live latency; `src/vaultspec_rag/graph_cache.py, search, service.py, _service_eviction.py, tests`.
- [x] `S02` - Profile and optimize canonical graph calculation separately while preserving graph and filesystem safety semantics; `Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core graph, config, core/corpus_io.py and covering tests`.

## Parallelization

Sequential: finish and verify S01 before graph-calculation changes in S02.

## Verification

S01: cold and expired reads return while construction is held by an event; concurrent
reads start one builder; invalidation is immediate; invalidated completion cannot
publish; failure retry is bounded; closed caches cannot republish. Canonical graph
ranking remains correct when ready. Run package lint, changed-file format and types,
and covering tests. Verify cold and warm live service query timings after deployment.

S02: measure scan, validation, construction, and cache restore separately on the real
vault. Optimize the measured dominant work, preserve graph nodes/edges and unsafe-path
refusals, and rerun the relevant canonical-owner tests and same-corpus timings.
