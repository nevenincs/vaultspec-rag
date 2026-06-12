---
tags:
  - '#exec'
  - '#cli-service-operability-hardening'
date: '2026-06-12'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-11-cli-service-operability-hardening-code-review-audit]]'
---

# `cli-service-operability-hardening` `W05` summary

Wave 05 integrated the CLI/service operability hardening into one product-facing
workflow and closed the review findings discovered during final validation.

- Modified: `src/vaultspec_rag/cli/_service_lifecycle.py`
- Modified: `src/vaultspec_rag/cli/_service_jobs.py`
- Modified: `src/vaultspec_rag/cli/_service_logs.py`
- Modified: `src/vaultspec_rag/cli/_http_search.py`
- Modified: `src/vaultspec_rag/server/_routes.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/server/_models.py`
- Modified: `src/vaultspec_rag/service.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/search/_searcher.py`
- Modified: `src/vaultspec_rag/tests/`
- Modified: `.vault/audit/`
- Modified: `.vault/exec/`
- Modified: `.vault/plan/`
- Created: `.vaultspec/rules/rules/service-domain-owns-operability.md`
- Created: `.vaultspec/rules/rules/cli-operability-needs-persona-tests.md`
- Created: `.vaultspec/rules/rules/operator-views-are-bounded.md`

## Description

The final integrated surface now gives a maintainer one coherent path through service
orientation, active work inspection, logs, search, timeout diagnosis, and request
correlation.

The shipped behavior includes:

- `server status --port` as the canonical explicit-port operator check,
- readiness-only `server health` with serving PID, interpreter, virtualenv, model, and
  reranker state,
- bounded and filterable `server jobs` output with focused job inspection,
- job records with initiator, user, process, memory, and CUDA resource context,
- `server logs` filters for `job_id` and arbitrary text,
- service-backed search responses with `index_state`, `request_id`, and phase timings,
- timeout diagnostics that include health, active jobs, backend concurrency, and next
  actions,
- numeric GPU queue-wait timing,
- request ids that can be joined back to service logs,
- shared reranker preload during service startup so the first project lease no longer
  pays the largest observed CrossEncoder setup cost.

Code review found and fixed the final rollout issues recorded as CR-13 through CR-16:

- stale `service.json` could block an explicit healthy port status check,
- filtered logs could miss a matching line outside the unfiltered tail,
- reranker preload made the old 30-second start wait budget too optimistic,
- reranker readiness was initially JSON-only and not directly covered by lifespan tests.

Manual persona validation used the resident service on port `8766`. The current service
was deliberately restarted when the implementation changed and left running afterward.

Representative commands:

- `uv run vaultspec-rag server status --json --port 8766`
- `uv run vaultspec-rag server status --port 8766`
- `uv run vaultspec-rag server health --json --port 8766`
- `uv run vaultspec-rag server health --port 8766`
- `uv run vaultspec-rag server jobs --limit 5 --port 8766`
- `uv run vaultspec-rag server logs --json --contains service.lifecycle --lines 1 --port 8766`
- `uv run vaultspec-rag search "server status jobs logs search timeout diagnostics" --type code --json --max-results 2 --port 8766 --timeout 180`
- `uv run vaultspec-rag search "cold reranker preload project lease timing" --type code --json --max-results 1 --port 8766 --timeout 180`
- `uv run vaultspec-rag server logs --json --contains 1d11935dd18e4e258c955439653fb339 --lines 5 --port 8766`

Observed results:

- status and health showed the active serving daemon PID and `reranker_loaded: true`,
- human status and health tables showed `Reranker loaded: True`,
- jobs output was bounded and summarized current state,
- filtered logs returned matching lifecycle entries,
- successful service-backed search returned `request_id`, `index_state`, and timing,
- request ids were joinable back to service logs,
- first-search `project_lease_seconds` after reranker preload dropped from the earlier
  observed `~6.53s` to about `1.35s`.

Verification executed during the rollout:

- `uv run ruff check` on touched Python files,
- `uv run ty check` on touched Python files,
- `uv run --no-sync python tools/complexity_gate.py`,
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`,
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_state.py`,
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`,
- `uv run pytest src/vaultspec_rag/tests/test_cli.py -k SearchTimeoutDefaults`,
- `uv run pytest src/vaultspec_rag/tests/test_service_registry.py::TestHealth src/vaultspec_rag/tests/test_service_registry.py::TestSharedReranker src/vaultspec_rag/tests/integration/test_service_lifecycle.py::test_start_health_stop`,
- pre-commit hooks on every pushed commit, including Ruff, Ty, complexity, markdown,
  provider-artifact, spec, and vault checks.

Residual risks:

- Cold service startup still takes tens of seconds because readiness now includes real
  shared model setup.
- The checker for the narrative epic plan still reports the pre-existing structural
  mismatch that the document has Wave headings but no `tier:` frontmatter and no
  checker-shaped Phase containers.
- A future diagnostic or doctor command is still justified, but this epic hardened the
  existing status, jobs, logs, health, and search surfaces instead of adding a new
  umbrella command.
