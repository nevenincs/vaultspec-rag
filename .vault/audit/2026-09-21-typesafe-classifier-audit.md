---
tags:
  - '#audit'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:d39726dec52ef8e185d6a7a102f1f43a0011cb651714a4b20430c5d44f3a7a59'
related:
  - "[[2026-09-21-typesafe-classifier-plan]]"
  - "[[2026-09-21-typesafe-classifier-adr]]"
---

# `typesafe-classifier` audit: integrated hosted search review

## Scope

Integrated final review of S01–S04 against 2026-09-21-typesafe-classifier-plan and its accepted decision: hosted transport and answer validation, query/candidate policy, direct and public search, explicit filtering, configuration, regression tests and live development spikes. The earlier independent review and delta review cover the unchanged final source. The final disposition below also covers the user's delegated quality/latency choice. Result: PASS, with no unresolved critical/high findings and the recorded ranking and observability limitations.

## Findings

### diagnostics-boundary | medium | Direct combined search includes caller notes in hosted state

At src/vaultspec_rag/search/_searcher.py:1265, all options enter constraints, including notes. Diagnostic values can be transmitted externally and suppress inferred preference. Exclude notes before constructing state. Assigned to S03 for correction and regression coverage.

### opaque-diagnostics | medium | Excluded notes are deep-copied before exclusion

At src/vaultspec_rag/search/_searcher.py:1092, asdict resolves the notes field before the comprehension drops it. A caller notes mapping containing threading.Lock raises even with no key. Materialize permitted fields without copying notes. Assigned to S03.

### zero-result-enrollment | medium | Public combined zero-budget searches make unnecessary paid calls

At src/vaultspec_rag/_public_search.py:400, a nonempty query with top_k=0 enters query classification. Align enrollment with the direct-path positive-budget guard while preserving existing argument validation. Assigned to S03.

### successful-evaluation-counters | low | Failed provider attempts are not counted as completed evaluations

At src/vaultspec_rag/search/_typesafe_policy.py:61 and :192, query failure returns None and candidate request counters advance only on successful evaluation. A timed-out request can still incur provider usage. These diagnostics are not a billing meter. Document successful-evaluation semantics or add bounded failure counters in a future observability refinement; do not expose provider bodies or keys.

### ranking-evidence | medium | Compound-query top-three target remains unproven in the production path

The live comparisons and unresolved production case are owned by 2026-09-21-typesafe-classifier-research. Deterministic unit tests do not establish ranking quality. S04 remains open until the selected policy is exercised through the actual production path; no claim of real-corpus retrieval superiority follows from fixture candidates.

### integration-delta | low | Three boundary findings are resolved

The follow-up integrated review confirms notes are excluded before field access in src/vaultspec_rag/search/_searcher.py:1091 and before combined constraints at :1268; public combined enrollment uses a positive-budget guard in src/vaultspec_rag/_public_search.py:401. Regression guards each failed under the named mutation and passed after restoration. The independent reviewer found no new critical/high findings. Preparation result remains PASS; remaining live-policy quality work is not waived.

### live-search-assertion-scope | low | Live composition checks have bounded claims

At dev/typesafe_search_spike.py, the requested-test assertion proves presence in the returned top five, not top-one accuracy; the cross-reference assertion proves source diversity, not every source's exact relevance or ordering. Calls go through actual prepare_query, rank and transport, and fallback results cannot pass. These checks complement but do not replace the ten-case production ranking evaluation.

### final-disposition | low | Bounded implementation accepted with visible quality limitations

The user delegated the quality/latency choice on 2026-09-21; the orchestrator retained the accepted bounded batched implementation without changing its deadline, thresholds or evaluation assertions. The selected path has been exercised by the live production-policy and actual search-orchestration experiments in 2026-09-21-typesafe-classifier-research. The ranking-evidence finding remains an accepted medium quality limitation, not a passing benchmark or a correctness-test waiver. The three integration boundary findings are resolved. The successful-evaluation-counters finding remains low; diagnostics are not billing totals. Final review result: PASS. No new code changes followed the independent delta review, and all required implementation checks pass.

### indexed-candidate-budget | high | Common filtered searches never reach hosted candidate ranking

The completed real indexed-service comparison in 2026-09-21-typesafe-classifier-research establishes that the selected top_k15 path-filtered workflow always falls back before candidate evaluation. The larger legacy retrieval window preserved by src/vaultspec_rag/search/_typesafe_policy.py:139 conflicts with the64-candidate rejection at :154; src/vaultspec_rag/search/_searcher.py:957 passes the whole surviving window. This is not a provider outage or uncertain model judgment. Existing fixture checks missed the realistic cross-boundary candidate count. Reopen S03. A correction needs a coherent bounded classification window and explicit regression coverage for path-filtered candidate expansion while preserving exact legacy fallback. No implementation correction is authorized by the current measurement-only task. Current integrated disposition: REVISION REQUIRED; this supersedes the earlier PASS for the newly exercised workflow.

### comparative-capture | low | Measurement completed with explicit limits and raw evidence

The two thirty-search arms preserve identical queries, source HEAD, index generation and response arrays; warmups are excluded from the reported timings. Live query calls and deterministic candidate-budget fallback are distinguished from completed candidate ranking. Original exact-name ranks remain in raw artifacts; supplemental overlap ranks are labeled and do not replace the original records. No production ranking changes were made. The benchmark client strips service tokens from status snapshots. The measurement itself is complete, but it does not demonstrate a functioning Typesafe-versus-vanilla candidate-ranking comparison.

### live compound-query deadline | high | Serial batches poisoned subsequent classification availability

The f4da6cdf indexed run successfully classified 32 candidates on eight measured requests, then compound-query batch work exhausted the shared ten-second budget. Two requests fell back and twenty bypassed classification during cooldown. This is not a completed quality comparison. Raw evidence is retained in tmp/typesafe-service-ab-f4da6cdf/on.jsonl. S01 and S02 were reopened and corrected: paired batches retain the two-call global transport bound and original deadlines; search-budget exhaustion no longer marks the credential/provider unavailable. Authentication/payment and genuine transport/schema failures retain their circuit behavior. The correction passes 150 targeted tests; live verification remains required under S06. Result: REVISION REQUIRED pending that verification.

### compound request packing | high | Paired calls alone did not fit repeated rubrics

The 0602d358 follow-up again reached genuine candidate judgments for focused cases but its four-clause request fragmented into many small batches; grouping_and_order exhausted the budget. The run was interrupted rather than presented as completion and remains under tmp/typesafe-service-ab-0602d358. Inspection and a failing unit guard also proved that URLError-wrapped timeouts still poisoned availability when search-limited; the live failure did not yet expose a reason counter, so this wrapper is a demonstrated code defect, not a proven attribution of that specific response. Correction expands only candidate JSON preflight from 24KB to64KB while retaining eight candidates, process-wide two-call capacity and all time limits; query preflight stays24KB. It handles wrapped timeout provenance and adds safe reason counters. All153 targeted tests and explicit static gates pass. Live verification remains open.

### live integration corrections | low | Prior activation and deadline findings resolved

At source00ce3f06, all30 indexed keyed searches completed32 full-content candidate classifications, including all repeated compound cases; none fell back or bypassed classification. The complete evidence and semantic judgments reside in2026-09-21-typesafe-classifier-research, completed indexed-comparison section. This resolves the prior high candidate-budget and compound-deadline integration findings for the exercised workflow. Review confirms unchanged keyless execution, atomic fallback, explicit filter authority, no unclassified-tail score mixing, bounded network concurrency and unchanged elapsed limits.153 targeted tests and explicit static gates pass. No credential was persisted. Result: PASS, with the quality and generalization limitations below.

### evidence coverage | medium | Compound pages remain incomplete and retain adjacent noise

The broad grouping/order question still lacks the formatter body, and the false-premise query places direct counterevidence below the top five despite improving over vanilla. Single grouping queries still promote locale deduplication and requested-test pages retain tests of a different document. These are measured quality limitations, not activation failure. Do not advertise complete facet coverage or general accuracy from this fixed ten-query corpus. The user's delegated bounded-batching quality/latency choice remains applicable; follow-on quality work needs separate representative evidence, not relabeling these misses.

### benchmark controls | low | Rebuilt generations limit strict replay claims

Both completed arms use identical frozen source, corpus size, query protocol and bounded freshness; runtime readiness required separate rebuilds after restart. Retain the generation identifiers and earlier failed attempts, and report a semantic repeated-query comparison rather than an identical-generation deterministic replay. The service readiness checks were not weakened to permit empty results. Result: PASS with this disclosed limitation.

### HTTPS connection reuse | medium | Search latency includes avoidable client overhead

The user's latency challenge prompted a real transport probe, documented in2026-09-21-typesafe-classifier-research. Warm persistent requests took about232ms/252ms versus current fresh-connection601ms/780ms for query/eight-candidate contracts. Connection setup alone cost325-336ms. The implementation recreates its HTTPS connection per request, and five requests form three serial stages per search. Preserve the successful classification/quality result, but do not attribute its4.13-second median to Typesafe inference or present it as optimized transport latency. Connection reuse remains an unimplemented optimization; this diagnostic made no production change. Result: PASS with this performance finding, not a claim of completed latency optimization.

### pooled-transport-review | low | Fresh-connection overhead resolved with bounded reuse

S07 integrated review traces enrollment through connection leases, exact-response reuse, duplicate admission, provider validation, policy accounting and existing direct/service timing surfaces. TLS verification and redirect refusal remain intact; sockets are exclusively leased, failed sockets discarded, active calls remain bounded by the existing two-slot gate, and slot release precedes waiter publication. Credential/circuit checks precede cache serving, rotation clears reuse, stale success cannot populate a new credential's cache, and follower timeout cannot cancel the paid owner. Responses are independently decoded for each caller. No persistent source/key cache or new provider retry is introduced. Mutation-proven expiry, full-payload cache identity and reuse guards supplement the existing deadline/enrollment tests.

### incomplete-http-frame | medium | Framing validation added before answer reuse

Review found that a peer could close after syntactically valid JSON but before its declared Content-Length was complete. The new real-loopback regression failed because no error was raised, then passed after the explicit remaining-length check. The transport now rejects incomplete framing, closes response resources on every path, and neither caches the answer nor retains that connection. Resolved within S07; no authority or schema change.

### timing-and-cost-scope | low | Work sums and elapsed time are explicitly distinguished

Local reranking now has a separate timer on all three surfaces; query-attempt duration survives enrollment failure and direct-search fallback retries are timed. Query/candidate phase counters distinguish validated network evaluations from cache hits and coalesced callers. Parallel request subphase values are sums, not additive wall time. Documentation explicitly excludes failed/unknown provider charges from these counters; they are not a billing ledger. Detailed timing contains no submitted content or credential.

### performance-verification-scope | low | Live production-path evidence is stage-specific

The follow-up uses actual provider responses and production policy over saved candidate fixtures, with live search-orchestration checks across all surfaces. Numeric comparisons and experiment limitations reside in the feature research. It does not replace or claim a new full GPU-backed service A/B; earlier quality limitations remain. Final review result: PASS, with no unresolved high or critical findings in S07.

## Recommendations

Retain the bounded opt-in implementation and exact legacy fallback. Preserve the authored live evaluation and its failure output so future ranking changes can be compared honestly. A future source-isolation proposal should establish bounded latency and concurrency on realistic candidate counts before changing deployment behavior. Representative indexed-corpus evaluation is the next quality measurement; it was not needed to develop or test the classifier without CUDA. Failed-attempt diagnostics can be refined without exposing credentials, provider bodies or source content.
