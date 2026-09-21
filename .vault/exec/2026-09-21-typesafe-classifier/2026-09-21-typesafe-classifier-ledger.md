---
tags:
  - '#exec'
  - '#typesafe-classifier'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:42bc7b86342ee0512e77ee3c3a610e5bddd99916ffc4719325e0ca4a01a6a0ec'
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

## Notes

- `S01` Transport guards mutation-proven fail then restore/pass. An early cap mutation sent a fake credential and synthetic payload to provider; subsequent fault tests enforce loopback. No real credential exposed. Commit awaits resolution of pre-existing shared hook conflicting with repository no-generated-config rule.
- `S02` 36 policy tests pass and guard mutations restored. Expanded live quality is 9/10, recorded under S04. Implementation and decision refinement are uncommitted pending shared-hook resolution.
- `S03` 40 tests pass. Mutation proofs: old only-prod normalization 4 fail then 4 pass; raw-query enrollment 8 fail then 8 pass; omitted notes clearing 1 fail then 1 pass; repeated combined CrossEncoder 1 fail then 1 pass. All mutations restored. Commit pending shared-hook resolution.
- `S04` Actual hosted evaluation: 9/10; formatter retained rank4 rather than required top3 on grouping/order. 33 requests, 91348 input and 10381 output tokens, 1.952-3.285 seconds/case. Standalone method comparison evidence lives in research. Combined targeted unit/regression run 182 pass; all18 touched Python files format/type clean and package plus spikes lint clean. Real-store integration tier refused collection without a resident GPU service; none started. Final integrated review, quality resolution and commits remain open.
- `S01` User authorized worktree-only hook adjustment. An exact gitdir conditional includes classification-only hook settings pointing to an empty directory; main and busyport retain default hooks. No shared hook was modified and no repository-wide worktreeConfig extension was enabled. Earlier commit blocker resolved; explicit gates remain required.
- `S04` Awaiting user preference: retain bounded batched production with documented 9/10 quality miss, or pursue isolated candidate ranking with bounded parallelism and a larger latency budget. S02-S04 remain open; no failed quality target relaxed.
- `S02` User delegated quality/latency decision; retained accepted bounded batching with unchanged authored evaluation and documented ranking miss. No assertion, threshold or deadline relaxed.

