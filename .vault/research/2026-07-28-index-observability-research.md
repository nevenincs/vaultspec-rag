---
tags:
  - '#research'
  - '#index-observability'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:995c369835f349c20edb3553c0bb9b2f3c5122e08739868a92752ebc8dd7f302'
related:
  - "[[2026-07-28-convergence-cost-research]]"
---

# `index-observability` research: `A starved encode pass is indistinguishable from a hang`

A live incident on 2026-07-28: a vault index job froze at 192/4609 in "embed + upsert
documents" for over five minutes while the operator watched the jobs TUI. Every surface
said nothing was wrong - `stalled: false`, no error, no log line, no backend signal -
and the operator concluded the previously-suspected hidden Qdrant failure had returned.
The actual cause was GPU starvation by unrelated processes; the job later succeeded
unmodified (`+2113 /0 -0` in 535s) once the card was freed. The question this grounds:
what must the job surfaces report so a starved-but-healthy run, a backend fault, and a
genuine hang stop looking identical.

## Findings

### Progress only ticks at slice boundaries, so one slow slice reads as a hang

The vault encode loop reports progress per encoded-and-upserted slice
(`src/vaultspec_rag/indexer/_streaming.py:820`); inside a slice the only activity is
the model forward pass. Under GPU contention (100% utilization, 15.5/16 GiB resident,
~36 processes holding CUDA contexts) one forward pass stretched from milliseconds to
minutes, so `progress.completed` sat at 192 - a slice boundary - with
`last_updated` aging past 300s. A `py-spy` dump proved the encode thread actively
inside `transformers` rotary-embedding code the whole time; nothing was wedged.

### The stall detector never fired

The jobs route computed `stalled: false` and `progress_rate_per_second: null` while
`last_progress_age_seconds` exceeded 245. Whatever threshold the stall flag uses, a
multi-minute silent embed phase did not trip it, and the TUI renders no wall-clock
since-last-progress indicator of its own, so the operator had no signal short of
reading raw JSON.

### The known failure channel logs an event with no error in it

The service log carries repeated `service.watcher event=reindex_failed ... state=running error=null` ERROR lines (multiple occurrences on 2026-07-28 alone). An error event
whose error field is null and whose state is `running` is the "hidden error condition"
operators remember but cannot act on: it names neither a cause nor a remediation, and
nothing correlates it to a job outcome surface.

### No backend-health signal reaches the job surfaces

During the incident the Qdrant log showed sub-10ms 200s and then silence - the backend
was healthy and idle - but the TUI offers no Qdrant liveness or last-write signal, so a
starved encoder and a write-refusing backend produce the same blank screen. The
operator's working hypothesis (Qdrant degradation) was wrong precisely because the one
surface that could distinguish the two shows neither.

### GPU contention is invisible to the job model

The job snapshot records CUDA memory at start (`resources.started`) and nothing
thereafter. Machine-wide GPU pressure - here, a 12-worker test fleet loading CUDA
models plus ~18 resident stdio MCP shims - is exactly the condition that produces
these freezes, and no surface samples utilization or resident memory during the run.

### Not investigated

- Whether the document and code streaming loops share the same slice-boundary-only
  progress cadence (expected but unverified).
- What threshold the `stalled` flag actually implements and why it did not fire.

## Sources

- `src/vaultspec_rag/indexer/_streaming.py:721`, `:820`
- `src/vaultspec_rag/indexer/_vault_indexer.py:709`
- Live evidence 2026-07-28: jobs route snapshot (job `9003ea45`, `last_progress_age_seconds=245.9`, `stalled=false`), `py-spy` thread dump of the daemon, `nvidia-smi` (100% util, 15486/16376 MiB), managed Qdrant log tail, service log `reindex_failed error=null` events at 13:03-13:32.
