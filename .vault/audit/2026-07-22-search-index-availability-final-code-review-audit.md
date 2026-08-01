---
tags:
  - '#audit'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:5a5708dce549ffdd98d64dbad679755aab189c899ae6bcbeede21771312779c9'
related:
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-07-21-search-index-availability-plan]]"
---

# `search-index-availability` audit: `final code review`

## Scope

This review covers the exact implementation authority at
`94b4600fdec57c6ba6ece013755fbe05b8cdfd63` and
`fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3`. It compares the committed
classification, route, consumer, and regression paths with the accepted architectural decision,
repository rules, issue intent, and immutable acceptance evidence.

The review evaluates exact canonical root/source/state evidence, response-boundary-first
deduplication, bounded operator evidence, nonempty-result preservation, collection-disappearance
recognition and rethrow behavior, body/status/log consistency, shared client and Model Context
Protocol propagation, test integrity, and shared-main campaign isolation.

## Findings

No critical, high, or medium finding remains.

The canonical classifier requires a nonempty ID, index operation, exact normalized source and
resolved root, accepted mode, and canonical nonterminal state. The second observation is ordered
first and deduplicated by exact job ID. Availability and rebuild state are computed from the
complete unique set before response evidence is capped at eight with explicit truncation.

Only an empty matching outcome becomes the declared HTTP 503 envelope; useful nonempty results
remain HTTP 200. The Qdrant correction accepts only a structured collection-missing 404 and only
when the same exact canonical evidence makes the synthetic empty observation unavailable. Every
declined backend response is re-raised. Normal and recovered paths share one frozen
classification for response, watcher, metrics, and bounded log correlation.

The shared client preserves structured failure bodies and the MCP adapter raises an actionable
recoverable error before result validation. Focused tests import production code and use real
`JobManager` and `UnexpectedResponse` objects. The lifecycle test uses real subprocess services,
Qdrant, models, official MCP transport, canonical persistence, and isolated singleton storage;
it introduces no fake, mock, stub, patch, monkeypatch, skip, or expected failure.

Ruff was clean; BasedPyright reported zero errors, warnings, or notes; 33 focused and 116 adjacent
tests passed; and local subprocess-GPU acceptance passed with one selected test and seven
deselected in 59.90 seconds. Both implementation commits have narrow declared scope, pass diff
hygiene, and remain ancestors of shared main.

## Recommendations

- Preserve the real Qdrant red trace as evidence for the nondeterministic collection-drop window.
- Keep `availability_cause` internal to logging and the public failure envelope stable.
- Retain the five-party rebuild barrier and separate persisted-paused restart phase.
- Leave durable generation-ledger authority with the large-index-resilience feature.

No blocking recommendation remains.
