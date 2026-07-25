---
tags:
  - '#plan'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-25'
tier: L2
related:
  - '[[2026-07-24-index-throughput-research]]'
  - '[[2026-07-24-index-throughput-adr]]'
---

# `index-throughput` plan

### Phase `P01` - GPU-job admission gate

One machine-wide admission slot for encode-bearing index jobs in the service job-dispatch layer, honest queued state on the job records, and a mutation-proven guard test.

- [x] `P01.S01` - implement the machine-wide encode-job admission gate in the job dispatch layer with honest queued state stamped on job records; `src/vaultspec_rag/server/job_dispatch.py`; job records\`.
- [x] `P01.S02` - add admission-gate tests including the mutation proof: bypass the gate, the concurrency assertion goes red on the intended assertion, restore green, both directions recorded; `src/vaultspec_rag/tests/` job-control suite\`.
- [x] `P01.S14` - stamp admission-acquired time on job records and accumulate per-job GPU-lock wait via a timed-acquire helper, publishing both through the existing jobs envelope so queued-shown-as-running is fixed; `src/vaultspec_rag/server/job_manager.py`; `src/vaultspec_rag/server/job_models.py`; `src/vaultspec_rag/indexer/_streaming.py`; `src/vaultspec_rag/embeddings.py`.

### Phase `P02` - explicit ingest wait policy

Non-blocking upsert semantics on the rebuild path with a completion barrier before stale-purge and metadata publish, measured before/after, guard test proving the barrier binds.

- [x] `P02.S03` - pass explicit non-blocking wait semantics on rebuild-path upserts and add the completion barrier before stale-purge and metadata publish; `src/vaultspec_rag/store.py`; indexer terminal paths\`.
- [x] `P02.S04` - add ingest-barrier tests including the mutation proof: remove the barrier, the terminal-state-precedes-applied-points assertion goes red, restore green, both directions recorded; `src/vaultspec_rag/tests/` store/indexer suites\`.
- [x] `P02.S05` - measure ingest wall-clock before and after the wait-policy change on a rebuild-class corpus and record the numbers; `measured run; Step Record`.
- [ ] `P02.S15` - switch the server-mode store client to gRPC transport and record the measured per-batch upsert delta; `src/vaultspec_rag/store.py`.

### Phase `P03` - vault and document pipeline overlap

Move vault parsing into the spawn-safe CPU worker pool and adopt the code path's bounded-queue producer/consumer for the vault and document encode paths, preserving the single-GPU-consumer contract; re-tune flush cadence once overlap exists.

- [x] `P03.S06` - move vault document parsing into the spawn-safe CPU worker pool keeping every worker torch-free; `src/vaultspec_rag/indexer/_vault_indexer.py`; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P03.S07` - adopt the bounded-queue producer/consumer pattern for the vault encode path with sentinel shutdown and time-bounded joins; `src/vaultspec_rag/indexer/_streaming.py`; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `P03.S08` - adopt the bounded-queue producer/consumer pattern for the document encode path with sentinel shutdown and time-bounded joins; `src/vaultspec_rag/indexer/_streaming.py`; document indexer\`.
- [ ] `P03.S09` - re-tune the CUDA cache flush cadence under overlap and record the measured effect; `src/vaultspec_rag/config.py`; measured run\`.
- [x] `P03.S10` - add overlap tests including mutation proofs that the single-consumer contract binds: a second consumer or lock-held-across-non-forward mutation goes red on the intended assertion, restore green, recorded; `src/vaultspec_rag/tests/` streaming suites\`.
- [x] `P03.S16` - apply the existing flush-cadence throttle to the vault slice path, which currently empties the CUDA cache every slice; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P03.S17` - throttle the document per-file loop's cache release, which currently syncs the device every slice by defaulting release-cache on; `src/vaultspec_rag/indexer/_document_indexer.py`; `src/vaultspec_rag/indexer/_streaming.py`.

### Phase `P04` - measure, verify, land

Before/after wall-clock measurement of a contended window and a rebuild-class job, full quality gates, and the commit-and-push landing.

- [x] `P04.S11` - run the before/after measurement: a contended multi-job window and a solo rebuild-class job, comparing wall-clock and queue-wait telemetry against the research baselines; `measured runs; Step Record`.
- [ ] `P04.S12` - run the full quality gates on the changed surface and fold measured numbers into the ADR consequences; `repository quality gates;`.vault/adr/2026-07-24-index-throughput-adr.md\`.
- [x] `P04.S13` - commit the throughput work with a why-focused message and push to origin main; `git`.
- [x] `P04.S18` - cap requires-python below 3.14 so the published metadata matches the runtime interpreter guard that already rejects 3.14, and add a .python-version pin so fresh worktree venvs resolve a supported interpreter; `pyproject.toml`; `.python-version`.

## Description

Execute the accepted throughput decision: bound encode-job admission to one machine-wide slot (P01), make ingest wait semantics explicit with a correctness barrier (P02), and align the vault and document encode paths with the code path's proven producer/consumer overlap plus worker-pool vault parsing (P03), then measure against the research baselines, verify, and land (P04). Grounded by the stage-decomposition research in related frontmatter; all GPU and storage rules invariant.

## Steps

## Parallelization

P01 and P02 touch disjoint surfaces (job dispatch vs store/indexer terminal paths) and may run in parallel. P03 hard-depends on nothing in P01/P02 functionally but shares `_streaming.py` with no one else, so it may start alongside them under single-writer file ownership. P04 is strictly last. Fleet constraint: exactly one coder agent and one optimizer/verifier agent; phases are therefore executed as sequenced batches per agent rather than a wide fan-out.

## Verification

- Admission gate: a contended window shows at most one encode-bearing job in flight, others honestly queued; mutation proof recorded (gate bypassed -> red on the concurrency assertion -> restored green).
- Ingest barrier: terminal metadata never precedes applied points (test-asserted); mutation proof recorded; before/after ingest wall-clock measured.
- Overlap: vault/document paths encode slice N+1 while slice N upserts; single consumer thread and forwards-only lock asserted by test; mutation proofs recorded.
- Before/after measurement shows contended-window wall-clock collapsing toward serial-sum and a solo rebuild not regressing.
- ruff, format, basedpyright, ty, complexity, citation gates and affected suites green; work committed and pushed to origin main.
- Plan complete when every Step is closed.
