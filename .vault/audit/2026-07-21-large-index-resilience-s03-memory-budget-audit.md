---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `large-index-resilience audit: W01.P01.S03 enforceable memory budget`

## Scope

Independent resource-safety, concurrency, compatibility, and import-boundary review of the
final `W01.P01.S03` enforcing memory budget in `memory_probe.py`.

## Findings

### mutable-admission-ceilings | high | Ordinary assignment could weaken a live budget

The first revision stored ceilings in assignable slots, so a caller could raise or remove an
admitted limit after construction and allow readings above the original ceiling. The final
budget rejects ordinary public or private assignment and deletion while retaining controlled
internal snapshot and latch updates.

### fail-open-enforcing-sample | high | Unavailable RSS could be admitted as zero

The first enforcing sampler reused optional observation helpers that deliberately map missing
or unreadable measurements to zero. A configured positive ceiling could therefore admit an
unmeasurable process. Strict nullable samplers now fail closed with stable typed RSS or CUDA
outcomes, while the legacy observation API keeps its compatibility behavior.

### unlatched-concurrent-violation | high | Racing observations could overwrite a breach

The first revision published a snapshot under the lock but classified it after releasing the
lock. A later observation could replace the exact violating label and current values, then
return success. Snapshot publication, deterministic classification, and the first-failure
latch now occur atomically; every later caller raises the identical typed failure.

Final review found no unresolved critical, high, medium, or low findings. Exact thresholds,
RSS precedence, CUDA allocated and reserved enforcement, peaks, violation retention, toggle
independence, unavailable paths, snapshot immutability, and legacy behavior passed direct
production probes. A 32-thread race, safe live observation, six focused tests, Ruff, ty,
BasedPyright, import-light inspection, and diff checks passed.

Status: **PASS** after revision.

## Recommendations

Construct one budget from admission-frozen configuration and call it only at the planned safe
boundaries outside `gpu_lock`; do not substitute the optional observation probe for enforcement.
