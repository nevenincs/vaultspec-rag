---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-W02-P05-S14]]"
---

# `service-job-control` audit: `s14 code publication protection`

## Scope

Audited the S14 protection added to clean and incremental codebase indexing.
The review covered exact protected-span boundaries, pending signal delivery,
application-error fidelity, batching and progress preservation, storage and GPU
lock ordering, and preservation of the bounded S13 producer/consumer lifecycle.

## Findings

No Critical or High findings.

The clean span enters before `drop_code_table` and encloses collection
recreation, the joined producer/consumer pipeline, stale cleanup, and atomic
metadata publication. Pending control is delivered at the normal protected
exit; application failures leave abnormally and are not masked by control.

Both incremental paths leave scan, hash, chunking, and old-ID discovery outside
protection. `_publish_incremental_replacement` protects the existing batched
delete, replacement slices, and metadata publication only when modified or
deleted files are present. New-only work retains normal slice-level control.
The whole-change-set span is a conservative superset of each file's invalid
interval and preserves cross-file GPU batching and the atomic metadata sidecar.

Progress phases, store calls and lock order, S13 cleanup and exception
precedence, single-consumer ownership, CPU-only worker imports, and encode-only
GPU locking remain unchanged.

## Recommendations

Proceed with S15's permanent real-behavior code indexing control coverage,
including resource unwind and resume convergence around these protected spans.
