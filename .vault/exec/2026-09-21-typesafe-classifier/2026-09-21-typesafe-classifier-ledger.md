---
tags:
  - '#exec'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:3723e30a72558c253f17edbcfdc80d5555933402672cc76576f5a7f8c8d2e789'
related:
  - "[[2026-09-21-typesafe-classifier-plan]]"
---

# `typesafe-classifier` ledger

## Changes

- `S01` `A` `src/vaultspec_rag/search/_typesafe_transport.py`
- `S01` `A` `src/vaultspec_rag/search/_typesafe_answers.py`
- `S01` `A` `src/vaultspec_rag/tests/test_typesafe_transport.py`
- `S01` `M` `src/vaultspec_rag/config/_types.py`
- `S01` `M` `.env.example`
- `S01` `verify:` `pytest test_typesafe_transport.py test_env_example_coverage.py (48 tests)` -> `pass`
- `S01` `verify:` `.venv/Scripts/python.exe -B -m ruff check src/vaultspec_rag` -> `pass`
- `S01` `verify:` `.venv/Scripts/python.exe -B -m ruff format --check src/vaultspec_rag/search/_typesafe_transport.py src/vaultspec_rag/search/_typesafe_answers.py src/vaultspec_rag/tests/test_typesafe_transport.py src/vaultspec_rag/config/_types.py` -> `pass`
- `S01` `verify:` `.venv/Scripts/python.exe -B -m basedpyright src/vaultspec_rag/search/_typesafe_transport.py src/vaultspec_rag/search/_typesafe_answers.py src/vaultspec_rag/tests/test_typesafe_transport.py src/vaultspec_rag/config/_types.py` -> `pass`
- `S01` `verify:` `.venv/Scripts/python.exe -B -m pytest -q src/vaultspec_rag/tests/test_typesafe_transport.py src/vaultspec_rag/tests/test_env_example_coverage.py` -> `pass`
- `S02` `A` `src/vaultspec_rag/search/_typesafe_policy.py`
- `S02` `A` `src/vaultspec_rag/search/_typesafe_questions.py`
- `S02` `A` `src/vaultspec_rag/tests/test_typesafe_policy.py`
- `S02` `verify:` `.venv/Scripts/python.exe -B -m pytest -q src/vaultspec_rag/tests/test_typesafe_policy.py` -> `pass`
- `S03` `M` `src/vaultspec_rag/search/_searcher.py`
- `S03` `A` `src/vaultspec_rag/search/_typesafe_context.py`
- `S03` `M` `src/vaultspec_rag/search/_noise.py`
- `S03` `M` `src/vaultspec_rag/_public_search.py`
- `S03` `A` `src/vaultspec_rag/tests/test_typesafe_search.py`
- `S03` `M` `src/vaultspec_rag/tests/test_search_noise.py`
- `S03` `verify:` `.venv/Scripts/python.exe -B -m pytest -q src/vaultspec_rag/tests/test_typesafe_search.py src/vaultspec_rag/tests/test_search_noise.py` -> `pass`
- `S04` `A` `dev/typesafe_evaluation.py`
- `S04` `A` `dev/typesafe_query_spike.py`
- `S04` `A` `dev/typesafe_chaining_spike.py`
- `S04` `A` `dev/typesafe_relation_spike.py`
- `S04` `A` `dev/typesafe_clause_spike.py`
- `S04` `verify:` `.venv/Scripts/python.exe -B dev/typesafe_evaluation.py` -> `fail`
- `S01` `M` `docs/configuration.md`
- `S01` `verify:` `python -B -m pytest -q test_configuration_doc.py test_env_example_coverage.py (9 passed; two documentation guards first failed for missing key row)` -> `pass`
- `S01` `verify:` `precommit: package Ruff lint, four S01 Python files Ruff format and basedpyright, transport plus environment/documentation tests (55 passed)` -> `pass`
- `S04` `A` `dev/typesafe_search_spike.py`
- `S04` `A` `.vault/audit/2026-09-21-typesafe-classifier-audit.md`
- `S04` `verify:` `dev/typesafe_evaluation.py live rerun after request-prefix normalization (9 of 10, formatter rank4)` -> `fail`
- `S03` `verify:` `public zero-budget and notes privacy/deepcopy guard mutations: intended failures then restored passes, worker final suite pending` -> `pass`
- `S04` `verify:` `python -B dev/typesafe_search_spike.py real hosted query and candidate calls through synthetic-retrieval VaultSearcher (5 of 5)` -> `pass`
- `S04` `verify:` `targeted transport, policy, search, noise, document shaping, parser, environment and configuration suites (215 passed); package lint and all19touched Python format/type checks` -> `pass`
- `S04` `verify:` `python -B dev/typesafe_evaluation.py after leading-whether normalization (9 of 10; formatter4 despite retained fullcontent)` -> `fail`
- `S04` `verify:` `dev/typesafe_clause_spike.py single-candidate live mode (4 of 4 difficult cases; 44calls, no retries)` -> `pass`
- `S02` `verify:` `package Ruff lint, three policy files format and basedpyright, 57 policy tests` -> `pass`
- `S03` `verify:` `package Ruff lint, six integration files format and basedpyright, 103 search/noise/shaping/parser tests` -> `pass`
- `S04` `verify:` `final package and six spike Ruff lint, spike format and basedpyright, 215 targeted tests; integrated safety review no unresolved high or critical findings` -> `pass`
- `S05` `A` `dev/typesafe_service_benchmark.py`
- `S05` `M` `.vault/research/2026-09-21-typesafe-classifier-research.md`
- `S05` `M` `.vault/audit/2026-09-21-typesafe-classifier-audit.md`
- `S05` `verify:` `.venv/Scripts/python.exe -B dev/typesafe_service_benchmark.py --mode off/on --port 18766 --output tmp/typesafe-service-ab-cbde33a3` -> `pass`
- `S03` `M` `src/vaultspec_rag/search/_typesafe_policy.py`
- `S03` `M` `src/vaultspec_rag/tests/test_typesafe_search.py`

## Notes

- `S01` Transport guards mutation-proven fail then restore/pass. An early cap mutation sent a fake credential and synthetic payload to provider; subsequent fault tests enforce loopback. No real credential exposed. Commit awaits resolution of pre-existing shared hook conflicting with repository no-generated-config rule.
- `S02` 36 policy tests pass and guard mutations restored. Expanded live quality is 9/10, recorded under S04. Implementation and decision refinement are uncommitted pending shared-hook resolution.
- `S03` 40 tests pass. Mutation proofs: old only-prod normalization 4 fail then 4 pass; raw-query enrollment 8 fail then 8 pass; omitted notes clearing 1 fail then 1 pass; repeated combined CrossEncoder 1 fail then 1 pass. All mutations restored. Commit pending shared-hook resolution.
- `S04` Actual hosted evaluation: 9/10; formatter retained rank4 rather than required top3 on grouping/order. 33 requests, 91348 input and 10381 output tokens, 1.952-3.285 seconds/case. Standalone method comparison evidence lives in research. Combined targeted unit/regression run 182 pass; all18 touched Python files format/type clean and package plus spikes lint clean. Real-store integration tier refused collection without a resident GPU service; none started. Final integrated review, quality resolution and commits remain open.
- `S01` User authorized worktree-only hook adjustment. An exact gitdir conditional includes classification-only hook settings pointing to an empty directory; main and busyport retain default hooks. No shared hook was modified and no repository-wide worktreeConfig extension was enabled. Earlier commit blocker resolved; explicit gates remain required.
- `S04` Awaiting user preference: retain bounded batched production with documented 9/10 quality miss, or pursue isolated candidate ranking with bounded parallelism and a larger latency budget. S02-S04 remain open; no failed quality target relaxed.
- `S02` User delegated quality/latency decision; retained accepted bounded batching with unchanged authored evaluation and documented ranking miss. No assertion, threshold or deadline relaxed.
- `S04` Closed under the user's delegated choice of bounded batching. Historical live evaluation failures remain recorded and the 9/10 benchmark remains unchanged; accepted quality limitation, not an all-green accuracy claim. No CUDA service or credential persistence.
- `S05` Real-service benchmark setup: frozen source HEAD cbde33a35d46a24e538296c000b6d38b3c992343. Isolated managed runtime, Qdrant storage and DATA_DIR under tmp/typesafe-service-ab-cbde33a3; service port 18766 and Qdrant 18765. Verified cached Qdrant executable against provisioned manifest and committed archive pin before copying managed binary/manifest. Initial startup attempts hit ownership/port conflicts; foreign services left untouched. Incremental indexing into fresh isolated publication storage correctly required explicit rebuild. Rebuild job 41dfc628-92ff-4e96-a7dd-4c213986dccb started against 832 admitted source files. No A/B measurements captured yet; concurrent CI GPU processes observed.
- `S05` Verification blocked before A/B captures: isolated rebuild stalled at 237/832 files inside CUDA forward while two foreign CI processes shared effectively full GPU. Cooperative pause remained pending; owned service PID58800 stopped successfully on port18766. No foreign processes stopped; no classifier-enabled arm or quality measurements captured. Await idle-GPU window; S05 remains open. Benchmark-client lint/format/type pass, actual live capture not yet exercised.
- `S05` Completed real indexed-service comparison, 30 measurements per arm plus warmup; raw artifacts and summary retained in ignored tmp/typesafe-service-ab-cbde33a3. All paired result arrays exactly equal. All keyed requests completed live query evaluation but hit candidate-budget fallback; zero candidate ranking completions. High integration finding reopens S03; no implementation fix made. Authorized RAG runner launcher/listener stopped and resident start/stop scheduled tasks disabled; remain disabled pending user direction. Benchmark service stopped after both arms. Existing classifier/noise tests:148 passed; package lint, benchmark format/type and unchanged-source check pass.
- `S05` User requested semantic rather than programmatic quality judgments. Added manual per-query content assessment, distinguishing direct evidence, useful context, wrong-operation near-matches, missing facets, buried counterevidence and failed no-match abstention. Exact equality is reported only as an observation of this capture; no determinism or model-quality claim.
- `S03` Authorized candidate-budget correction separates the full locally reranked retrieval pool from a hosted prefix with rejection headroom. top_k15 selects32 complete candidates after local reranking. Same selection applies to code, vault and document lanes; unclassified tail is never score-mixed back. New real-policy regression with150 path-filtered candidates failed on missing typesafe_candidates under old integration and passed after correction, proving selection occurs after local reranking. 149 targeted tests, package lint and touched-module type checks pass. Live verification continues in S06; no ranking-quality claim yet.
