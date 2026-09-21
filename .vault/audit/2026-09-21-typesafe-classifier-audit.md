---
tags:
  - '#audit'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:2382afd680b75556c063e7f7f2cc132d399669d210c117da395076a8dd30dee9'
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

## Recommendations

Retain the bounded opt-in implementation and exact legacy fallback. Preserve the authored live evaluation and its failure output so future ranking changes can be compared honestly. A future source-isolation proposal should establish bounded latency and concurrency on realistic candidate counts before changing deployment behavior. Representative indexed-corpus evaluation is the next quality measurement; it was not needed to develop or test the classifier without CUDA. Failed-attempt diagnostics can be refined without exposing credentials, provider bodies or source content.
