---
tags:
  - '#audit'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-07-21-search-index-availability-plan]]"
  - "[[2026-07-21-search-index-availability-reference]]"
---

# `search-index-availability` audit: `nonempty-result availability follow-up`

## Scope

This review covers the two-commit stack from `d8f1f1d` through `59a53d7`.
The stack contains `6d1498c` and `59a53d7`. The audit compares their exact diffs and
current production paths with the accepted architecture, plan, research, and reference.

The review evaluates successful nonempty and empty classification, snapshot precedence,
request-log consistency, canonical job identity, bounded evidence, known race windows, and
real-service acceptance. It also applies the service-domain and bounded-operator-view rules.

The verdict is **revision required**. The classifier preserves nonempty bodies and status,
and empty failures retain strict canonical, after-first, bounded evidence. One high and one
medium finding remain open.

## Findings

### second-observation-log-evidence | medium | Unavailable logs can omit their causal jobs

`search_route` derives `matching_index_jobs` and `matching_index_job_ids` only from the
admission snapshot. `_classify_search_result` captures a separate response-boundary snapshot.

A matching job can begin during retrieval. The second snapshot then produces HTTP 503 and
names that job in `index_state.matching_jobs`. The corresponding `service.search`
unavailable log still reports zero matching jobs and an empty identifier field.

The integration regression starts the rebuild before it admits every search. It therefore
cannot exercise this second-observation-only path. The log count also caps silently at eight
because it records the exposed reference count without a truncation field.

Acceptance requires one shared classification result for the response and request log. A
second-observation-only job must appear in both, with response-boundary evidence ordered before
admission-only evidence. Log correlation must remain capped at eight and state when matches
were truncated. A route-level regression must prove these outcomes.

### real-service-nonempty-acceptance | high | Required real-service coverage was replaced by a classifier unit test

`6d1498c` removes the baseline index, real matching incremental job, known-document search,
and HTTP assertion from `test_search_index_unavailable_during_matching_rebuild`. It replaces
them with `test_nonempty_result_remains_available_during_matching_rebuild`.

The replacement creates a paused canonical snapshot and passes an opaque nonempty dictionary
directly to `classify_search_response`. It proves the pure helper returns the same object with
status 200. It does not exercise search retrieval, the HTTP route, request logging, watcher
scheduling, real storage, real models, or overlap with a running index operation.

This change contradicts plan Step `W01.P05.S08`, which requires a real-service assertion.
It also removes the matching-nonempty probe from the accepted architectural regression matrix.

Acceptance requires a real subprocess service, real storage, real models, and a real matching
nonterminal job for the exact root and source. Search a known indexed document while that job
overlaps the request. Assert HTTP 200, at least one real matching result, a completed status-200
request log, and bounded correlated job evidence. Keep the CPU unit as focused classifier
coverage, and retain every empty-result, client, and Model Context Protocol assertion.

## Recommendations

1. Return one bounded classification-evidence object from the service-domain helper. Use it
   for both the HTTP body and `service.search` log fields.
1. Add a route-level second-observation regression that verifies matching identifiers,
   after-first ordering, the eight-job cap, and explicit truncation in logs.
1. Restore the real-service matching-nonempty acceptance without removing the focused CPU
   classifier unit. Use a real job mode that preserves an already published result.
1. Re-run the targeted subprocess-GPU regression, adjacent search suites, Ruff, BasedPyright,
   and feature-specific Vaultspec checks before accepting the stack.

## Resolution

The historical revision-required verdict above is retained as review evidence. Commit
`94b4600fdec57c6ba6ece013755fbe05b8cdfd63` resolves both findings. One frozen
`SearchResponseClassification` now drives the response body, HTTP status, watcher, and bounded
`service.search` evidence. Response-boundary matches are ordered first, duplicate IDs use that
newer state, exposure is capped at eight with explicit truncation, and rebuild status is computed
from the complete pre-cap match set.

The real-service nonempty contract now runs as a separate restart phase. After a real clean index
is published, the daemon stops, a matching rebuild is persisted in `paused` state, and the daemon
restarts against the same storage. A known document remains a nonempty HTTP 200; the completed log
names the exact paused job; and the job revision is unchanged.

Final immutable acceptance at `fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3` passed Ruff,
BasedPyright with zero errors, warnings, or notes, 33 focused tests, 116 adjacent tests, and the
local real-Qdrant/GPU regression with one passed and seven deselected in 59.90 seconds. No finding
in this historical audit remains unresolved.
