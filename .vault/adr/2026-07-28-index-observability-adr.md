---
tags:
  - '#adr'
  - '#index-observability'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
related:
  - "[[2026-07-28-index-observability-research]]"
---

# `index-observability` adr: `Degradation truth for long encode phases` | (**status:** `accepted`)

## Problem Statement

A GPU-starved encode pass, a write-refusing backend, and a genuinely hung job are
indistinguishable on every operator surface for up to five minutes, and partially
indistinguishable forever after (`2026-07-28-index-observability-research`). The system
cannot make a foreign-saturated GPU fast; the decision is what truth the job surfaces
owe an operator while work is degraded, and through which mechanism.

## Considerations

- Progress currently ticks only at slice boundaries; a slice's forward pass is opaque
  and can legitimately run minutes under contention.
- The `stalled` flag exists with one 300-second threshold shared by every surface, and
  carries no cause when it fires.
- The GPU discipline permits read-only CUDA probes with guarded function-local imports
  on paths that must tolerate a torch-free host, and forbids new GPU consumers.
- The service surface rule requires service-domain behaviour with CLI and MCP adapted
  to it - degradation classification must live in the service, not the TUI.
- The `reindex_failed` ERROR event fires on non-terminal transitions with a null error,
  poisoning the one channel operators grep for real failures.

## Considered options

- Phase-runtime telemetry plus service-side degradation verdict (chosen): the encode
  path publishes forward-entry/exit timestamps and slice context; the jobs surface
  classifies `healthy` / `degraded` / `stalled` and attaches sampled evidence (GPU
  utilization and memory, backend probe latency, encode-thread activity) when not
  healthy. Pro: no change to model-call structure; verdict and evidence live in the
  service domain. Con: degraded-versus-stalled depends on sampling fidelity.
- Sub-batching the sentence-transformers call to heartbeat between sub-batches:
  rejected - it forfeits the library's length-sorted padding optimisation and couples
  progress cadence to batch tuning, and a single slow sub-batch still goes silent.
- Auto-deferring index jobs when the GPU is foreign-saturated: rejected for now -
  admission policy changes behaviour under a signal we have just started measuring;
  revisit once degradation evidence has accumulated.
- TUI-side heuristics over `last_progress_age`: rejected - the CLI already fell back to
  exactly this and it cannot attribute cause; entry points must not own the verdict.

## Constraints

- Evidence sampling must never touch the GPU as a consumer: utilization and memory come
  from read-only probes that report absence rather than raise, and the sampler must be
  torch-free-host safe.
- The backend probe must be bounded and cheap (an exists/count with a short timeout)
  so a dead backend cannot wedge the surface reporting on it.
- Every addition rides the existing enriched jobs projection so CLI, TUI, and MCP
  inherit one contract; no second vocabulary.
- The 300-second stall threshold stays as the hard verdict; the new degraded tier must
  fire meaningfully earlier without flapping on healthy short pauses.

## Implementation

The encode slice records phase runtime: entering and leaving each forward publishes a
timestamp, slice ordinal, and item count into the job's runtime block through the
existing progress reporter plumbing. The jobs enrichment adds a three-way
`degradation` verdict beside `stalled`: `healthy` while progress or forward activity is
recent; `degraded` when a forward has been running or progress has been absent beyond a
short threshold; `stalled` at the existing hard threshold. When the verdict is not
healthy the service attaches an evidence block - forward age, GPU utilization and
resident memory from the read-only probe, a bounded backend liveness probe with
latency, and whether the encode worker thread is alive - so the TUI renders cause, not
just silence. The watcher's non-terminal observation stops logging `reindex_failed`;
the terminal path logs it with the error it actually has. The TUI and CLI jobs
presentation render the verdict and evidence verbatim from the service payload.

## Rationale

The chosen mechanism reports truth from where truth exists: the process that owns the
forward pass and the store client. It changes no compute behaviour, so it cannot
regress indexing, and it converts the incident's five silent minutes into a verdict
with attached cause within the degraded threshold. Alternatives either move the verdict
into entry points (forbidden by the service-surface rule), trade padding efficiency for
cadence, or change admission behaviour on unproven signal.

## Consequences

- Operators can distinguish starved-but-alive, backend-fault, and hung within the
  degraded threshold, with evidence rather than inference.
- The service log's ERROR channel regains meaning once `reindex_failed` fires only on
  terminal failures with a populated error.
- Sampling adds a small bounded cost to the jobs surface only while a job is unhealthy.
- Auto-defer under saturation remains open; the evidence block this record introduces
  is the input a future admission decision needs.
