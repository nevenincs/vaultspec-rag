---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-W02-P05-S14]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

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
