---
tags:
  - '#research'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:8c3a400d8a50225b49231457244301e71caaa6a2b472b344debdb850339838a0'
related: []
---

# `typesafe-classifier` research: Jev search classification

The question is whether hosted classification can improve retrieval precision without making search depend on a paid API. Documentation inspected on 2026-09-21 supports an optional classification stage with application-owned routing and conservative abstention; improvement on this code corpus remains unmeasured.

## Findings

### Typed decisions support distinct ranking and routing signals

Choice returns a categorical answer and distribution; Score returns the expectation over ordered descriptive levels, not a normalized relevance probability. Both carry confidence. Noul returns the probability of one proposition and has no separate confidence. Low confidence calls for fallback; thresholds depend on the action and must be evaluated on domain data. Sources: https://docs.typesafe.ai/primitives/score ; https://docs.typesafe.ai/primitives/noul ; https://docs.typesafe.ai/confidence .

### Compose independent questions together and true dependencies in code

Questions share state but do not see one another's answers. Structured instructions can directly identify a candidate inside nested state. Independent intent, wording, domain and evidence questions can be batched. Hierarchical menus whose options depend on a preceding answer require another request. The hierarchy cookbook explores several paths and ranks them by geometric mean edge probability; this is a traversal heuristic, not calibrated joint confidence. For a small fixed domain taxonomy, speculative questions avoid unnecessary serial requests. Sources: https://docs.typesafe.ai/primitives ; https://docs.typesafe.ai/primitives/advanced ; https://docs.typesafe.ai/cookbooks/hierarchical_classification .

### Relevance filtering needs protection against false negatives

The reranking cookbook compares query-candidate pairs using Noul. The passage-classification cookbook separates relevance, answer evidence and contradiction; contradictory evidence can be useful. Its thresholds are corpus-specific. Applying its prompt-injection exclusion verbatim to code search risks hiding legitimate security tests and examples. Evidence favors relevance and usefulness judgments evaluated against the requested intent, with deterministic explicit filters remaining outside model control. Sources: https://docs.typesafe.ai/cookbooks/rerank_typesafe ; https://docs.typesafe.ai/cookbooks/classifying_rag_passages .

### Model limits favor bounded candidate sets and a pinned version

Current model is `jev-1.13.0`; `jev-latest` is a moving alias. Published context limits are 64k request tokens and 32k for state plus the longest question. Large irrelevant state, indirection, numeric reasoning and adversarial text are documented weaknesses. Send complete candidate content within a bounded request, keep arithmetic and invariants in code, and evaluate prompt edge cases. A larger retrieval pool need not become one giant model state. Sources: https://docs.typesafe.ai/models ; https://docs.typesafe.ai/model-jaggedness/jev-1.13 .

### Usability requires an evaluation, not merely a configured credential

The public HTTP contract documents POST `https://api.typesafe.ai/v1/systemone`, bearer authentication, and errors including 401, 422, 429 and 529. Model listing does not document a credit balance. No credit-status endpoint was found in the documentation index or API reference inspected. One authorized synthetic evaluation succeeded on 2026-09-21 with `jev-1.13.0`, 431 input tokens, 72 output tokens and 792 ms client elapsed time. This confirms usability at that instant, not a remaining balance. The credential was read into process memory and removed afterward; no credential is recorded here. Source: https://docs.typesafe.ai/api ; https://docs.typesafe.ai/models .

### A smoke call does not establish ranking quality

The smoke state paired the query `retry backoff around failed webhook delivery` with an abbreviated pseudo-implementation. Choice selected implementation at confidence 0.97; usefulness Score was 1.79 of 2 at confidence 0.68; the stricter implementation Noul was 0.27. These are differently scoped judgments, not interchangeable evidence. The next evaluation needs labeled complete snippets, irrelevant near-matches, uncertain cases, false premises, explicit domain filters, and cross-reference requests. No live CUDA service is needed to test those classifier and orchestration contracts. End-to-end retrieval recall requires a later representative indexed corpus evaluation.

### Query wording guides retrieval strategy rather than validity

Qdrant documents semantic and lexical retrieval as complementary: natural-language intent and exact identifiers can benefit from different retrievers. Its hybrid-query documentation supports query-dependent weighting and evaluation-based tuning. No universal noun-only query-validity rule was found. Wording classification can provide a routing signal but should not reject natural-language queries or invent a generated rewrite. Sources: https://qdrant.tech/documentation/search/text-search/hybrid-search/ ; https://qdrant.tech/documentation/search/hybrid-queries/ .

### Live full-function baseline reveals compound-query and abstention failures

The 2026-09-21 run of dev/typesafe_evaluation.py used real jev-1.13.0 answers for eight authored queries against ten complete functions extracted from this checkout. Candidate starting scores were fixed fixtures, not measured legacy retrieval scores. Six of eight predefined checks passed: fusion, noise policy, grouping, combined sorting, test lookup and feedback IDs. Compound status/domain cross-reference failed: apply_status_filter remained rank 9 and partition_hard_domains rank 7. The unrelated AES-GCM invoice query retained two irrelevant hits despite dropping eight. Source: dev/typesafe_evaluation.py, CASES and run_case; observed live output. Per-query elapsed time was 1.958–2.293 seconds. The draft policy anchors uncertain judgments to baseline positions, which can leave direct evidence behind uncertain distractors; prompts and batching also require controlled comparison. These results do not validate the current policy or establish improvement over real retrieval.

### Explicit category definitions outperform bare labels in the routing spike

Two live runs of dev/typesafe_query_spike.py compared domain Choice labels, descriptive Choice alternatives and three independent Noul membership questions. Descriptive Choice selected the authored domain on all eight queries in both runs. In the first run, the test query's bare-label confidence was 0.81 versus 1.0 with descriptions, and the mixed production/test query was 0.74 versus 0.98. Independent Noul routing at the predefined 0.8 threshold passed seven of eight: the three-source cross-reference request scored only 0.44 production, 0.71 tests and 0.23 documentation, losing all three sources. Many small questions alone do not guarantee correct routing. Source: dev/typesafe_query_spike.py, CASES, DOMAINS and ATOMIC; observed live output. First run: 13 requests, 46 questions, 7,219 input and 1,481 output tokens.

### A conditional source hierarchy recovered missed cross-reference branches

The second routing run used descriptive parent Choice to choose follow-up questions. A mixed parent caused separate requested/excluded/unmentioned Choice questions for production, tests and documentation; accepted requested branches then received source-specific evidence-form questions. The cross-reference case recovered all three requested sources at confidence 0.97, 0.99 and 0.96. Finer snippet/assertion/decision judgments had confidence 0.78, 0.36 and 0.90: parent certainty does not justify forcing a child answer. An unmentioned documentation branch in the production/test case had confidence only 0.22, so it must not become a hard exclusion. Source: dev/typesafe_query_spike.py, membership_questions and followups; observed live output. Second run: 16 requests, 55 questions, 9,128 input and 1,835 output tokens; 0.571–1.835 seconds per query. These authored cases are development probes, not held-out accuracy or calibration estimates.

### Naive chaining did not outperform independent passage questions

The first dev/typesafe_chaining_spike.py run made 80 real requests and 480 questions (87,830 input and 10,571 output tokens) across five cases and two methods. Each method passed three of five predefined checks. Independent passage questions put the cross-reference functions at ranks 1/2; chaining also put them at ranks 1/2. Both recovered feedback/fusion and the environment-variable test. The grouping/order/locator query failed: locator ranked 4 independently and 7 chained. The chained Noul facet gate selected only merging (0.88), missing grouping (0.17) and locator formatting (0.23). Both methods failed to empty the unrelated AES-GCM result set. Independent questions retained nine unrelated functions because vague contradiction probabilities of 0.20–0.38 blocked dropping despite relevance near 0.03 and unrelated probability near 1. Chaining retained all ten: its forced strongest-facet fallback selected domain filtering even though every query-facet score was at most 0.04, introducing unrelated context. Source: dev/typesafe_chaining_spike.py, independent, chained and Judgment; observed live output. Independent calls took 2.904–3.289 seconds/case; chained calls took 6.578–6.970 seconds/case.

The facet vocabulary was manually authored for this small corpus and is not a general-purpose query decomposer. Comparisons against dev/typesafe_evaluation.py also change prompts, batching, metadata and ranking treatment, so they do not isolate a single causal improvement. Evidence favors testing explicit relation categories, preserving unselected/unknown facets, and avoiding forced branches before adopting a chain in production. No calibration claim follows from these development cases.

### Explicit relations improve no-match filtering but can lose counterevidence

The first dev/typesafe_relation_spike.py live run passed two of four cases. It classified all ten AES-GCM distractors as unrelated at confidence 1.0 and recovered both cross-reference functions. However, format_locator was wrongly labeled unrelated for the false sorting premise (confidence 0.70) and the compound grouping query (0.75), and the experimental 0.5 retention threshold dropped it. No candidate received the refutes label, so the proposed answer-dependent refutation check ran zero times; that run supplies no evidence for that conditional branch. A separate facet comparison still misclassified the requested grouping facet as unmentioned at confidence 0.88. Source: dev/typesafe_relation_spike.py, initial_relations, verify_refutations and facet_membership; observed live output. Total: 30 requests, 120 questions, 29,297 input and 4,177 output tokens. This is evidence against using a confident parent category as an irreversible clause gate.

### Exhaustive literal clauses retained useful uncertainty and passed the difficult cases

The first dev/typesafe_clause_spike.py live run tested grouping/order/formatter, a false sorting premise, status/domain cross-reference and the unrelated AES-GCM control. Both initial clause judgments and optional rechecks passed all four predefined checks. Initial grouping ranks were group 1, merge 2 and locator 3; the locator's usefulness probability was only 0.41, but low confidence prevented dropping it. The false-premise formatter ranked 3 with usefulness probability 0.70. The unrelated result set was empty. Rechecking every candidate's strongest clause did not improve the pass count and moved the domain-filter function from rank 1 to rank 3 in cross-reference. Initial latency was 2.387–2.567 seconds/case; rechecking added 2.364–2.684 seconds/case. Total: 32 requests, 130 questions, 64,493 input and 5,740 output tokens. Source: dev/typesafe_clause_spike.py, CASES, initial, recheck and run_case; observed live output.

These clauses were authored manually and checked as literal substrings. The experiment does not validate automatic clause extraction. Evidence favors a follow-up implementation using the full original query as a coverage backstop, bounded literal subclauses, soft probability-based ordering, and strong confidence requirements only for dropping. The same cases must next exercise that actual production path. Independent child questions may share a request; second-pass candidate rechecking has not earned its latency here.

### Automatic clauses pass the original eight cases but miss one expanded top-three target

The revised production path was exercised through dev/typesafe_evaluation.py, prepare_query and ClassificationSession.rank with the real provider. It passed all original eight cases and nine of ten after adding the compound grouping/order and false-premise cases. The remaining failure retains format_locator at rank 4 rather than the authored top-three target; group and merge occupy ranks 1/2 and hybrid fusion is rank 3. The false-premise formatter ranks 2. The AES-GCM no-match query drops all ten candidates. The test query now yields tests domain at confidence 0.98. No expected labels or acceptance thresholds were relaxed. Source: dev/typesafe_evaluation.py, CASES and run_case; src/vaultspec_rag/search/_typesafe_questions.py, query_clauses; observed live output. The live evaluation exits 1 for the remaining ranking failure. This is not a ready-to-claim perfect ranker or an end-to-end retrieval gain measurement; the deterministic fixture baseline is not a measured GPU reranker baseline.

## Sources

https://docs.typesafe.ai/introduction
https://docs.typesafe.ai/primitives
https://docs.typesafe.ai/primitives/score
https://docs.typesafe.ai/primitives/noul
https://docs.typesafe.ai/primitives/advanced
https://docs.typesafe.ai/confidence
https://docs.typesafe.ai/models
https://docs.typesafe.ai/api
https://docs.typesafe.ai/model-jaggedness/jev-1.13
https://docs.typesafe.ai/cookbooks/rerank_typesafe
https://docs.typesafe.ai/cookbooks/classifying_rag_passages
https://docs.typesafe.ai/cookbooks/hierarchical_classification
https://qdrant.tech/documentation/search/text-search/hybrid-search/
https://qdrant.tech/documentation/search/hybrid-queries/
