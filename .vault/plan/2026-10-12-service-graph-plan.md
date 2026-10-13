---
tags:
  - '#plan'
  - '#service-graph'
date: '2026-10-12'
tier: L1
related:
  - '[[2026-04-02-service-graph-adr]]'
  - '[[2026-03-07-vaultgraph-cache-adr]]'
modified: '2026-10-13'
body_schema: body-v2
body_hash: 'sha256:f5052dcbc62d26332a92910b563ecd8e0c816c3898fc83077100217f5403b460'
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
- [x] `S02` - Profile and optimize canonical graph calculation separately while preserving graph and filesystem safety semantics; `vaultspec-core/src/vaultspec_core graph, config, core/corpus_io.py and covering tests`.
- [x] `S03` - Profile cold graph construction with py-spy and process I/O, CPU, memory and handles; optimize measured work and verify cache and filesystem safety; `vaultspec-core/src/vaultspec_core/core/corpus_io.py, graph, config, scanner, covering tests and dev profiling instrument`.
- [x] `S04` - Repair integration failures exposed by full CI and verify the combined recovery and graph changes through one RAG pull request; `src/vaultspec_rag tests and affected canonical runtime owners, existing execution records`.

## Parallelization

Sequential: finish and verify S01 before graph-calculation changes in S02.

S04 uses parallel workers with disjoint ownership. Delegate recovery/checkpoint
integration tests and duplicate publication helpers to one worker; delegate graph
test substitution-discipline corrections to a second worker. The coordinator owns
install/workspace integration, shared configuration fixtures, browser failures,
package gates, records and the single RAG PR. Workers report targeted checks and
never commit shared records. Integrate before full-suite validation.

## Verification

S01: cold and expired reads return while construction is held by an event; concurrent
reads start one builder; invalidation is immediate; invalidated completion cannot
publish; failure retry is bounded; closed caches cannot republish. Canonical graph
ranking remains correct when ready. Run package lint, changed-file format and types,
and covering tests. Verify cold and warm live service query timings after deployment.

S02: measure scan, validation, construction, and cache restore separately on the real
vault. Optimize the measured dominant work, preserve graph nodes/edges and unsafe-path
refusals, and rerun the relevant canonical-owner tests and same-corpus timings.

S03: capture py-spy stacks and process CPU, I/O, RSS and handles on the real corpus.
Compare controlled cold runs, measure cached loads and PageRank separately, preserve
path safety and handle ownership with mutation-proven guards, run covering tests and
configured gates, and verify installed runtime hashes and live service searches.

S04 is authorized by the user's request to preserve landed work, correct CI and land
verified changes through PRs. Preserve existing recovery, path-security and graph
contracts. Diagnose the actual failed branches; do not weaken guards. Run targeted
regressions, package gates and the full CI matrix. Reuse existing core PR 606.
