---
tags:
  - '#plan'
  - '#typesafe-classifier'
date: '2026-09-21'
tier: L1
related:
  - '[[2026-09-21-typesafe-classifier-adr]]'
modified: '2026-09-21'
body_schema: body-v2
body_hash: 'sha256:37f8ead337591f672d8f9d1dbc065a9fbced6a11be32bb2f2e9e8d98265e807c'
---

# `typesafe-classifier` plan

Implement optional hosted query and candidate classification with legacy fallback.

## Description

Approved 2026-09-21

The user's explicit request authorizes the full pipeline, dedicated environment-key enrollment, query interpretation and result filtering/reranking, synthetic GPU-free tests, temporary process-only use of the supplied credential, and .env.example documentation. Governing decision: `2026-09-21-typesafe-classifier-adr`. The decision retains legacy search contracts outside its opted-in mode and scopes the hosted exception to existing ranking-authority and explicit-intent policies. No indexing schema or GPU provisioning changes are planned.

On 2026-09-21 the user explicitly delegated the quality/latency choice to the orchestrator. Retain the accepted bounded batched implementation; do not expand the deadline or adopt serial source isolation. The authored ranking evaluation remains unchanged and its known miss is retained as a documented quality limitation, not relabeled as passing. Comparative evidence belongs to 2026-09-21-typesafe-classifier-research. Implementation correctness and safety checks remain mandatory; this choice does not claim perfect ranking or measured indexed-corpus gains.

## Steps

- [x] `S01` - Implement bounded environment-enrolled hosted transport and strict typed answer validation with fallback state tests; `new search/_typesafe_transport.py and search/_typesafe_answers.py, transport tests, config/_types.py, .env.example and docs/configuration.md`.
- [x] `S02` - Implement atomic query and full-content candidate questions with confidence-aware routing and ranking policy; `new search/_typesafe_policy.py, search/_typesafe_questions.py and pure policy tests`.
- [ ] `S03` - Integrate bounded classification across direct and service search with exact legacy fallback and repair production-only hard filtering; `search/_searcher.py, search/_typesafe_context.py, search/_noise.py, _public_search.py, test_typesafe_search.py and test_search_noise.py`.
- [ ] `S04` - Compare independent atomic, nested, relation and literal-clause live-API spikes, then verify integrated behavior and resolve review findings; `dev/typesafe_evaluation.py, dev/typesafe_query_spike.py, dev/typesafe_chaining_spike.py, dev/typesafe_relation_spike.py, dev/typesafe_clause_spike.py, dev/typesafe_search_spike.py, classifier tests and feature audit`.

## Parallelization

S01 and S02 may be implemented concurrently: transport owns classifier transport/schema modules and transport tests; policy owns query/candidate question and policy modules and pure policy tests. S03 may prepare shared integration against those interfaces, but its close depends on S01 and S02 verification. The user's live-spike mandate brings S04 experiments forward before S02 policy is finalized: policy owns dev/typesafe_chaining_spike.py, the orchestrator owns query-routing and evaluation spikes, and transport may perform disjoint formatting-only support. No policy is considered validated by mocked provider answers. The orchestrator owns shared files and serializes plan, ledger and commit writes. Workers must not revert others' edits. Integrated review remains after implementation verification.

## Verification

Run package lint, formatting checks, type checks over touched modules, and targeted tests before each Step commit. Prove negative guard tests fail on their named regression and pass after restoring it. Unit fault tests cover keyless no-call behavior, invalid/payment credentials, transient failures, malformed/partial answers, uncertainty, candidate bounds, full-content handling, explicit filters, combined partial outcomes and exact legacy fallback after widening; they are not ranking-quality evidence. Use the existing .venv without GPU service startup. Per the user's subsequent mandate, ranking and query-routing experiments must call the real Typesafe API, never synthesized API answers. Standalone development spikes compare simple independent questions with genuinely answer-dependent chains over complete code functions, compound queries and predefined relevance labels before finalizing policy. Report failures, latency and token usage honestly. Completion requires all Steps closed and the integrated final audit passing; real indexed-corpus retrieval gains remain unmeasured.
