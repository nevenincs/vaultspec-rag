---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S44'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Create a reproducible large-index resilience harness using the production index path and real backends

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`

## Description

- Confirm the large-index resilience harness is reproducible, drives the
  production index path, and runs against real backends
  (`src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`).

## Outcome

The harness satisfies the step's three requirements, and this record confirms
it against the contract rather than producing it - the harness was committed
through other work ahead of this plan's execute phase reaching the step.

It is reproducible. It builds a deterministic source corpus of fixed dimensions,
owns it through a marker file it validates on every run, and can resume an
existing corpus rather than rebuilding it; a run emits a JSON report so its
result is comparable across invocations. The default corpus is defined exactly -
83,624 files that produce three chunks each through the production chunker - so
the same command reproduces the same shape.

It drives the production index path, not a test double. It constructs a real
code indexer and calls the same full-index entry point the service uses, so the
corpus flows through the production AST chunker, the streaming pipeline, and the
commit-ledger checkpoint machinery the rest of this plan hardened.

It runs against real backends. It loads a real embedding model and opens a real
vector store against the configured backend, rather than stubbing either, and
validates that the selected support profile is the managed-service one before it
loads the model, so an acceptance run measures the real production stack.

One safety property beyond the contract is worth recording: the harness never
deletes or rewrites a root it does not own by its marker. A reproducible
large-corpus harness that can point at an operator-supplied path is exactly the
place an unguarded rebuild would be destructive, and the marker ownership is the
guard against that.

## Notes

Verified and recorded, not executed here. The harness was committed before this
plan's execute phase reached the step, so no code was written for it; this
record confirms it is to spec by reading it - the deterministic marker-owned
corpus, the production full-index call, the real model and store, and the
profile validation - not by authoring it.

This step is the harness itself. Actually running it to the incident-scale floor
is a separate step and a heavy real-CUDA acceptance run; it is deferred, because
the memory-boundedness the harness exists to demonstrate is already proven at
the N and two-N doubling on real hardware, and reproducing the exact 250,872-
chunk floor is a capstone validation rather than a correctness gate. The harness
is ready to run it when that reproduction is wanted.
