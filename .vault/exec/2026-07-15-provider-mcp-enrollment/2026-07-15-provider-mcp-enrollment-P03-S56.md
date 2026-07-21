---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S56'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Bound real GPU fixture setup and metadata retries

## Scope

- `src/vaultspec_rag/embeddings.py`
- `src/vaultspec_rag/search/_searcher.py`
- `src/vaultspec_rag/tests/conftest.py`
- `src/vaultspec_rag/tests/_model_setup.py`
- `src/vaultspec_rag/tests/test_model_setup.py`
- `src/vaultspec_rag/tests/integration/test_intent_ranking.py`
- S55 release-gate diagnostics and the S56 independent review

## Description

- Add opt-in cache-only construction to the real dense, sparse, and lazy reranker model loaders while preserving online-capable production defaults.
- Validate cached Hugging Face snapshots offline for configuration, tokenizer assets, unsharded weights, or every shard named by a weight index.
- Acquire incomplete or cold snapshots in a dedicated process with a 600-second cold-session deadline, retained output tail, and terminate-to-kill escalation.
- Run the complete intent-ranking setup in one bounded worker: copy the full real vault, construct all real GPU models, index through production APIs, execute every labeled query, and return JSON evidence for the unchanged assertions.
- Add real loopback HTTP regressions for a request held open beyond the deadline and a persistent 504 response whose URL, status, and body remain visible.

## Outcome

S55's unbounded metadata path is closed without changing global pytest timeout semantics. Warm complete caches perform no remote metadata request, cold or interrupted caches retain bounded online repair, and product callers remain online-capable unless they explicitly request local-only loading.

The full quality contract remains intact: the worker copied and indexed all 1,111 real vault Markdown documents rather than selecting from gold judgments. With `HF_ENDPOINT` deliberately unreachable, the exact S55 selector passed in 36.91 seconds on the reduced diagnostic iteration, and the restored complete-vault four-test module passed in 131.71 seconds with a 131.00-second bounded fixture. The final combined model group passed 13 of 13 tests in 123.22 seconds, including complete-vault ranking, partial-cache timeout diagnostics, and real dense and sparse GPU behavior.

Verification completed successfully:

- Real metadata endpoint regressions: 2 passed.
- Complete intent-ranking module: 4 passed.
- Combined model and ranking group: 13 passed.
- Search and ADR regression group: 74 passed.
- Ruff on the affected surface, Ruff formatting on the affected surface, Ty, strict BasedPyright, complexity, and diff checks passed.
- Vault structure, frontmatter, links, placeholders, and encoding checks passed for the changed records.
- Independent S56 review closed one HIGH corpus-validity finding and one MEDIUM partial-cache finding; final verdict PASS with no actionable findings.

## Notes

Two early diagnostic iterations earned no test credit. The first proved cache-only dense and sparse construction completed in roughly 4.5 seconds but exposed the original 1,110-document setup outside a process boundary. The second proved the new 600-second boundary returned a normal pytest error with retained stage output under severe shared-GPU pressure.

GPU diagnostics identified a worktree-local orphan from `test_get_jobs_is_newest_first` on port 55108. Its absent parent, worktree interpreter, pytest-temporary Qdrant binary, and exact process ancestry established ownership; only that tree and its console hosts were terminated. The global service on port 8766 was left running. After cleanup, the unchanged 50-document diagnostic corpus completed in about 33 seconds and the restored complete-vault corpus completed in about 131 seconds.

A repository-wide Ruff format check still reports the unrelated pre-existing `src/vaultspec_rag/cli/_preprocess.py` formatting drift; every S56-touched file is format-clean. This step does not claim the complete platform release campaign, publication, or PR gates.
