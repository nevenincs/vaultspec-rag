---
tags:
  - '#adr'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:9262b500ecf041e77c08413174094b8fa0b20ef73fbbfa11e5e077e762658308'
related:
  - "[[2026-09-21-typesafe-classifier-research]]"
  - "[[2026-09-21-typesafe-classifier-reference]]"
  - "[[2026-06-30-search-noise-filtering-adr]]"
  - "[[2026-06-24-vault-pipeline-search-adr]]"
  - "[[2026-06-21-service-first-search-fallback-adr]]"
  - "[[2026-03-07-qdrant-filter-on-prefetch-adr]]"
  - '[[2026-09-23-status-messages-research]]'
---

# `typesafe-classifier` adr: optional hosted search classification | (**status:** `accepted`)

## Problem Statement

Add typed query and result judgments to search while preserving dependable operation when hosted classification cannot run. Grounding: `2026-09-21-typesafe-classifier-research` and `2026-09-21-typesafe-classifier-reference`.

## Considerations

Accepted 2026-09-21 under the user's advance authorization for the full integration, environment-key enrollment, query classification, result filtering and GPU-free synthetic development. This acceptance is scoped to the optional hosted mode.

The user's 2026-09-21 mandate authorizes automatic enrollment only through VAULTSPEC_RAG_TYPESAFE_API_KEY in the executing environment with a usable funded credential, confidence-aware query routing and result filtering, and GPU-free development using synthetic candidates. Existing explicit filters and partial-domain outcomes remain binding.

The internal classification policy was refined under the user's subsequent explicit mandate for live, small-question and chained-classification spikes. The accepted hosted boundary is unchanged. The comparative evidence and remaining quality miss reside in 2026-09-21-typesafe-classifier-research; this refinement does not assert universal ranking improvement.

## Considered options

- Keep the current ranker alone: preserves operation but does not deliver the requested classification signals.
- Replace local search globally or require a second enable flag: rejected because it violates environment-key opt-in and legacy fallback.
- Add a bounded optional hosted classification path with unchanged legacy execution on abstention or failure: selected. Existing retrieval remains responsible for candidate recall and explicit filtering.

## Constraints

Enrollment reads only the dedicated environment variable; no key in root-controlled configuration, request payloads or serialized diagnostics. A successful typed query evaluation establishes current usability. Authentication or payment rejection disables calls for that credential until rotation or process restart; transient failures use a bounded cooldown. No undocumented balance endpoint is assumed.

All network work stays outside GPU and storage locks, with bounded request size, concurrency and elapsed budget. Full candidate content is required; unavailable or oversized evidence abstains instead of substituting a display snippet. Never log response bodies, credentials or source content.

## Implementation

Use a torch-free classifier transport and pure question/policy modules, with a pinned Jev version. Validate every answer against the submitted question contract, including finite values, probability ranges, required keys and score levels. Candidate identities are local request keys and never model-authored replacements.

Classify query intent, desired evidence form, domain emphasis and wording with separate descriptive questions. Uncertain query classifications preserve existing defaults. Inferred intent may guide optional ranking and internal candidate allocation, but never overrides an explicit surface, intent, path, type, domain or feedback constraint. Keep all eligible combined domains reachable; cross-reference queries retain multi-domain evidence. Wording is advisory and never grounds query rejection or generated rewriting.

Classify bounded full-content candidate windows before irreversible grouping or final truncation where practical. Use small usefulness Choice questions against literal query clauses, retaining the complete original query as a coverage backstop. Clause extraction must not invent text or silently discard late requests; excessive splitting falls back to the original query. Query assessments become advisory input to candidate judgments in the next request. Independent clause questions may share one request; do not add a routine second candidate recheck without evaluation evidence for its cost.

Order fully classified survivors by usefulness probabilities with deterministic prior-order tie breaks. Ranking is a soft action; low confidence must not freeze a relevant candidate in its original slot. Dropping requires strong irrelevant judgments across every evaluated clause. Evidence useful for checking a false premise and uncertain evidence must remain eligible. Allow empty results when all candidates are confidently irrelevant. If any candidate cannot be scored with full content within the per-request or per-search limits, abstain for the whole surface and execute the original pipeline rather than mixing unclassified retrieval scores with hosted probabilities.

Candidate-pool growth is limited to the usable hosted path and bounded separately from returned top_k. On a failure after widening, execute the original query and original budget through the existing pipeline, restoring caller diagnostic notes as well as results. Keep explicit domain/status constraints, document identity, locators and partial failures intact. Share classification policy across direct and service combined search. Expose bounded operational counts, token usage and timings through existing diagnostics. Add the dedicated variable to .env.example with its external-data and fallback semantics.

## Rationale

The selected boundary implements the user's opt-in mandate while making uncertainty and provider availability ordinary fallback conditions. It introduces no CPU embedding path or persisted index schema. Research supplies the model semantics; the reference identifies where early truncation and combined-path differences need attention.

This is a distinct decision for the hosted mode. The CrossEncoder-primary and explicit-only intent constraints of `2026-06-30-search-noise-filtering-adr`, `2026-05-31-search-postprocess-adr` and `2026-06-24-vault-pipeline-search-adr` continue to govern the legacy mode. Under the authorized hosted mode, semantic classification can outrank and drop results, and confidently inferred intent can guide ranking when no explicit intent exists. Their deterministic filter and metadata contracts remain in force in both modes.

## Consequences

Search can shed confidently irrelevant candidates and adapt evidence ranking to query intent. It incurs external data transfer, paid requests and bounded added latency only when the dedicated key opts in. Synthetic tests can prove routing, filtering, fallback, schema validation and resource bounds without CUDA; they cannot establish real-corpus recall or a universal ranking improvement. Thresholds remain conservative until representative labeled evaluations support changes.
