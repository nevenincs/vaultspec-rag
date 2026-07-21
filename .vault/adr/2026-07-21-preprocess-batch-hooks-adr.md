---
tags:
  - '#adr'
  - '#preprocess-batch-hooks'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-preprocess-batch-hooks-research]]"
---

# `preprocess-batch-hooks` adr: `opt-in batch manifest invocation` | (**status:** `accepted`)

## Problem Statement

One subprocess per (file, rule) makes preprocess hooks dismally slow on first
index and clean rebuilds: the measured spawn constant is 102.7 ms/file for a
bare python hook and 217.3 ms/file through `uv run`, versus 1.2 ms/file when
one spawn handles 100 files (issue #241, research benchmark). The per-file
constant survives pool parallelism and the D7 cache only spares unchanged
files.

## Considerations

The v1 hook contract is public and must keep working unchanged. Hooks are
repo-authored code under the sandbox-removal trust model; the operating
guards are the output caps and the wall-clock timeout, and both must survive
batching. Workers stay CPU-only. Batching requires grouping matched files
per rule before pool dispatch.

## Considered options

1. **Opt-in batch manifest per spawn** (chosen). A rule sets `batch = true`;
   the runner writes N source paths to a manifest file, substitutes it for a
   `{paths}` token, and parses a JSON array of per-file v1 outputs.
2. **Persistent hook worker** (deferred escalation). One process per (rule,
   run) speaking line-JSON. Best amortization, but a full lifecycle contract
   (per-request timeout, kill-on-wedge, restart policy) - not needed until
   batch spawns are shown to still be hot.
3. **Guidance only** (rejected as the fix). Halves the constant at best.

## Constraints

- `batch = true` is valid only on `command` rules whose command carries the
  `{paths}` placeholder; config validation rejects `batch` with `{path}` or
  with `entry_point` (the entry-point form keeps v1 semantics).
- Batch timeout is `timeout_s * len(batch)`, capped at 600 s, so the
  per-file budget the author declared scales with the work handed over.
- The stdout cap scales with batch size the same way; the per-file
  emitted-text cap (D10) applies unchanged to every element.
- A batch element missing from the hook's response is treated as that
  file's failure and resolved through the rule's `on_error`, per file; a
  malformed envelope fails the whole batch through `on_error`, per file.
- Batch results are cached per file under the existing D7 key, so cache
  hits keep bypassing the hook entirely and mixed hit/miss sets shrink the
  manifest to the misses.

## Implementation

Batch grouping happens in the indexer glue before pool dispatch: matched
files for a batching rule are chunked into manifests of at most
`batch_size` (default 64) and each batch is one pool task; non-batch rules
and unmatched files keep the existing per-file flow. The runner gains a
batch entry point that writes the manifest to a temp file, invokes the
command once, validates the array envelope (`schema_version`, one v1 output
object per path), splits it into per-file `PreprocessResult`s, and writes
per-file cache entries.

## Rationale

The benchmark shows the spawn constant is the class problem and batching
removes ~99% of it for cheap hooks while never hurting heavy ones. The
manifest form is the smallest contract delta that preserves every v1 guard:
same JSON schema per file, same caps, same `on_error`, same cache key. The
persistent-worker option is strictly more powerful but pays a lifecycle
contract we have no evidence we need yet.

## Consequences

Hook authors opt in per rule and gain order-of-magnitude first-index
speedups; existing configs are untouched. The runner grows a second
invocation shape whose failure semantics are per-file, keeping skip/
passthrough/fail behavior identical to v1. If batch spawns remain hot for
some consumer, the persistent-worker escalation supersedes this ADR's
mechanism without changing rule configs beyond a new knob.
